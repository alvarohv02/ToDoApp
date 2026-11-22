#!/usr/bin/env bash
# Comprueba, paso a paso, todo lo que necesita el bot de WhatsApp y dice qué falla.
# Uso (en el servidor):  sudo bash /opt/notion/deploy/comprobar_whatsapp.sh [34600111222]
#   Con un número (con prefijo, sin +) además manda la plantilla de prueba "hello_world" a ese número.
# No muestra el token ni las claves del .env.
set -u

ENV=/opt/notion/.env
DOMINIO=${DOMINIO_BOT:-}
API=https://graph.facebook.com
VERDE=$'\e[32m'; ROJO=$'\e[31m'; AMARILLO=$'\e[33m'; NORMAL=$'\e[0m'
fallos=0
ok()    { echo "  ${VERDE}✓${NORMAL} $*"; }
mal()   { echo "  ${ROJO}✗${NORMAL} $*"; fallos=$((fallos + 1)); }
aviso() { echo "  ${AMARILLO}!${NORMAL} $*"; }
leer()  { grep -E "^$1=" "$ENV" | tail -1 | cut -d= -f2- | tr -d "\"' \r"; }
json()  { python3 -c "import json,sys
try: d=json.load(sys.stdin)
except Exception: sys.exit()
$1" 2>/dev/null; }

[ "$(id -u)" -eq 0 ] || { echo "Ejecútalo con sudo"; exit 1; }
[ -f "$ENV" ] || { echo "No encuentro $ENV"; exit 1; }

echo "1. Configuración del .env"
TOKEN=$(leer TOKEN); PHONE_ID=$(leer WHATSAPP_PHONE_NUMBER_ID); VERIFY=$(leer WHATSAPP_VERIFY_TOKEN)
PERMITIDOS=$(leer WHATSAPP_ALLOWED_NUMBERS); VERSION=$(leer WHATSAPP_API_VERSION); VERSION=${VERSION:-v23.0}
[ -n "$TOKEN" ] && ok "TOKEN puesto (${#TOKEN} caracteres)" || mal "Falta TOKEN"
[ -n "$PHONE_ID" ] && ok "WHATSAPP_PHONE_NUMBER_ID puesto" || mal "Falta WHATSAPP_PHONE_NUMBER_ID"
[ -n "$VERIFY" ] && ok "WHATSAPP_VERIFY_TOKEN puesto" || mal "Falta WHATSAPP_VERIFY_TOKEN"
[ -n "$PERMITIDOS" ] && ok "Números permitidos: $(echo "$PERMITIDOS" | tr ',' '\n' | sed 's/.*\(....\)$/…\1/' | paste -sd' ')" \
    || aviso "WHATSAPP_ALLOWED_NUMBERS vacío: solo contestará a usuarios aprobados en la web"
[ -n "$(leer WHATSAPP_APP_SECRET)" ] && aviso "Hay WHATSAPP_APP_SECRET: si está mal, la app rechaza a Meta sin dejar rastro (403 en nginx)"

echo "2. DNS e IP pública"
if [ -z "$DOMINIO" ]; then
    DOMINIO=$(grep -hoE "server_name\s+bot\.[^ ;]+" /etc/nginx/sites-enabled/* 2>/dev/null | awk '{print $2}' | head -1)
fi
IP_REAL=$(curl -s4 --max-time 8 https://ifconfig.me)
if [ -z "$DOMINIO" ]; then
    mal "No encuentro el dominio del bot en nginx (ponlo así: sudo DOMINIO_BOT=bot.tudominio.es bash ...)"
else
    # Se pregunta directamente al servidor DNS del dominio (sin cachés intermedias)
    NS=$(dig +short NS "${DOMINIO#*.}" | head -1)
    IP_DNS=$([ -n "$NS" ] && dig +short "$DOMINIO" "@$NS" 2>/dev/null | tail -1)
    [ -z "$IP_DNS" ] && IP_DNS=$(dig +short "$DOMINIO" | tail -1)
    IP_PUBLICA_DNS=$(dig +short "$DOMINIO" @1.1.1.1 | tail -1)
    if [ "$IP_DNS" = "$IP_REAL" ]; then ok "$DOMINIO apunta a tu IP actual ($IP_REAL)"
    else mal "$DOMINIO apunta a $IP_DNS pero tu IP es $IP_REAL (¿el DNS dinámico no se actualiza?)"; fi
    [ "$IP_PUBLICA_DNS" != "$IP_DNS" ] && aviso "Internet aún ve $IP_PUBLICA_DNS (la caché del DNS tarda unos minutos)"
fi
echo "3. nginx y la aplicación"
if [ -n "$DOMINIO" ] && [ -n "$VERIFY" ]; then
    RESPUESTA=$(curl -s --max-time 8 --resolve "$DOMINIO:443:127.0.0.1" \
        "https://$DOMINIO/webhook/?hub.mode=subscribe&hub.verify_token=$VERIFY&hub.challenge=prueba123")
    [ "$RESPUESTA" = "prueba123" ] && ok "El webhook responde bien dentro del servidor" \
        || mal "El webhook no responde como debe dentro del servidor (respuesta: ${RESPUESTA:0:80})"
    CERT=$(echo | openssl s_client -connect 127.0.0.1:443 -servername "$DOMINIO" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
    [ -n "$CERT" ] && ok "Certificado HTTPS válido hasta $CERT" || mal "No se puede leer el certificado HTTPS de $DOMINIO"
fi
UID_BOT=$(id -u notion_bot 2>/dev/null)
ESTADO=$(sudo -u notion_bot DOCKER_HOST="unix:///run/user/$UID_BOT/docker.sock" docker inspect -f '{{.State.Status}}' notion-bot 2>/dev/null)
[ "$ESTADO" = "running" ] && ok "El contenedor notion-bot está en marcha" || mal "El contenedor notion-bot no está en marcha (${ESTADO:-no existe})"

echo "4. Meta: token, número y webhook"
if [ -n "$TOKEN" ]; then
    NUMERO=$(curl -s --max-time 10 "$API/$VERSION/$PHONE_ID?fields=display_phone_number,verified_name,quality_rating" \
        -H "Authorization: Bearer $TOKEN")
    ERROR=$(echo "$NUMERO" | json "print(d.get('error',{}).get('message',''))")
    if [ -n "$ERROR" ]; then
        mal "Meta rechaza el token o el id del número: $ERROR"
    else
        ok "Token válido. Número del bot: $(echo "$NUMERO" | json "print(d.get('display_phone_number'), '·', d.get('verified_name'))")"
    fi
    INFO=$(curl -s --max-time 10 "$API/$VERSION/debug_token?input_token=$TOKEN" -H "Authorization: Bearer $TOKEN")
    CADUCA=$(echo "$INFO" | json "
datos=d.get('data',{})
import datetime
if not datos.get('is_valid'): print('')
elif not datos.get('expires_at'): print('nunca')
else: print(datetime.datetime.fromtimestamp(datos['expires_at']).strftime('%d/%m/%Y %H:%M'))")
    if [ "$CADUCA" = "nunca" ]; then ok "El token no caduca"
    elif [ -n "$CADUCA" ]; then aviso "El token caduca el $CADUCA (usa uno de usuario del sistema, que no caduca)"
    fi
    WABA=$(echo "$INFO" | json "
for s in d.get('data',{}).get('granular_scopes',[]):
    if s.get('scope')=='whatsapp_business_management':
        print((s.get('target_ids') or [''])[0]); break")
    if [ -z "$WABA" ]; then
        aviso "No puedo saber el id de la cuenta de WhatsApp Business con este token (no se comprueba la suscripción)"
    else
        APPS=$(curl -s --max-time 10 "$API/$VERSION/$WABA/subscribed_apps" -H "Authorization: Bearer $TOKEN")
        CUANTAS=$(echo "$APPS" | json "print(len(d.get('data',[])))")
        if [ "${CUANTAS:-0}" -gt 0 ]; then
            ok "La app está suscrita a la cuenta de WhatsApp ($(echo "$APPS" | json "print(', '.join(a.get('whatsapp_business_api_data',{}).get('name','?') for a in d['data']))"))"
        else
            mal "Ninguna app suscrita a la cuenta de WhatsApp: Meta no enviará mensajes al webhook"
            echo "      Arreglo: curl -s -X POST \"$API/$VERSION/$WABA/subscribed_apps\" -H \"Authorization: Bearer \$TOKEN\""
        fi
    fi
fi

echo "5. ¿Llega Meta al servidor?"
ULTIMO=$(grep -h "POST /webhook/" /var/log/nginx/access.log 2>/dev/null | tail -1)
if [ -n "$ULTIMO" ]; then
    echo "$ULTIMO" | awk '{print "  último aviso de Meta: " $4 "] → código " $9}' | tr -d '['
    case "$(echo "$ULTIMO" | awk '{print $9}')" in
        200) ;;
        403) mal "La app rechaza a Meta (403): revisa WHATSAPP_APP_SECRET o déjalo vacío" ;;
        *) mal "Respuesta rara al último aviso de Meta" ;;
    esac
else
    aviso "nginx no tiene ningún aviso de Meta en el log actual"
fi

if [ $# -ge 1 ] && [ -n "$TOKEN" ]; then
    echo "6. Envío de prueba a …${1: -4}"
    ENVIO=$(curl -s --max-time 10 -X POST "$API/$VERSION/$PHONE_ID/messages" -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"messaging_product\":\"whatsapp\",\"to\":\"$1\",\"type\":\"template\",\"template\":{\"name\":\"hello_world\",\"language\":{\"code\":\"en_US\"}}}")
    ERROR=$(echo "$ENVIO" | json "print(d.get('error',{}).get('message',''))")
    [ -z "$ERROR" ] && ok "Meta ha aceptado el mensaje: te tiene que llegar un \"Hello World\"" || mal "Meta no lo envía: $ERROR"
fi

echo
if [ $fallos -eq 0 ]; then
    echo "${VERDE}Todo en orden.${NORMAL} Escribe \"hola\" al bot y mira si llega con:  sudo tail -f /var/log/nginx/access.log | grep webhook"
else
    echo "${ROJO}$fallos cosa(s) que arreglar${NORMAL} (arriba, con ✗)."
fi
