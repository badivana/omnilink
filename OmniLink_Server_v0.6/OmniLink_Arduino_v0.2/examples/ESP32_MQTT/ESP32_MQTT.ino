#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <OmniLink.h>
#include <time.h>

// Set to 0 only for a private test broker/network. Plain MQTT exposes the device secret.
#define OMNILINK_MQTT_TLS 1
const char *SSID="YOUR_WIFI", *PASSWORD="YOUR_WIFI_PASSWORD";
const char *HOST="iot.example.com", *DEVICE_ID="dev_COPY_FROM_OMNILINK";
const char *DEVICE_SECRET="COPY_THE_64_CHARACTER_SECRET_ONCE";
#if OMNILINK_MQTT_TLS
const char ROOT_CA[] PROGMEM=R"CERT(-----BEGIN CERTIFICATE-----
PASTE_data/certs/ca.crt_CONTENT_HERE
-----END CERTIFICATE-----
)CERT";
#endif
const uint8_t RELAY_PIN=17; const bool RELAY_ACTIVE_LOW=true;
#if OMNILINK_MQTT_TLS
WiFiClientSecure network;
const uint16_t MQTT_PORT=8883;
#else
WiFiClient network;
const uint16_t MQTT_PORT=1883;
#endif
PubSubClient mqtt(network); OmniLink omniLink(mqtt);
bool reported=false, relayState=false;
bool masterPower(bool on){relayState=on;digitalWrite(RELAY_PIN,(on^RELAY_ACTIVE_LOW)?HIGH:LOW);return true;}
void setup(){
  Serial.begin(115200);pinMode(RELAY_PIN,OUTPUT);masterPower(false);
  WiFi.begin(SSID,PASSWORD);while(WiFi.status()!=WL_CONNECTED)delay(250);
  configTime(0,0,"pool.ntp.org","time.google.com");while(time(nullptr)<1700000000)delay(100);
  #if OMNILINK_MQTT_TLS
  network.setCACert(ROOT_CA);
  #endif
  omniLink.onBool(0,masterPower);
  omniLink.begin(HOST,MQTT_PORT,DEVICE_ID,DEVICE_SECRET,"omnilink-esp32-0.2");
}
void loop(){omniLink.loop();if(omniLink.connected()&&!reported){omniLink.reportBool(0,relayState);reported=true;}if(!omniLink.connected())reported=false;}
