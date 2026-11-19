#include <ESP8266WiFi.h>
#include <WiFiClientSecureBearSSL.h>
#include <OmniLinkHttp.h>
#include <time.h>

// For native Run/Install use https://host:8000 (shown below); for Docker/Caddy use https://host.
// Set to 0 only for a trusted private test network; HTTP exposes the device secret.
#define OMNILINK_HTTP_TLS 1
const char *SSID="YOUR_WIFI", *PASSWORD="YOUR_WIFI_PASSWORD";
#if OMNILINK_HTTP_TLS
const char *BASE_URL="https://iot.example.com:8000";
#else
const char *BASE_URL="http://iot.example.com:8000";
#endif
const char *DEVICE_ID="dev_COPY_FROM_OMNILINK";
const char *DEVICE_SECRET="COPY_THE_64_CHARACTER_SECRET_ONCE";

#if OMNILINK_HTTP_TLS
static const char ROOT_CA[] PROGMEM=R"CERT(-----BEGIN CERTIFICATE-----
PASTE_THE_CA_CERTIFICATE_TRUSTED_BY_YOUR_HTTPS_HOST_HERE
-----END CERTIFICATE-----
)CERT";
BearSSL::WiFiClientSecure network;
#else
WiFiClient network;
#endif
OmniLinkHttp<decltype(network)> omniLink(network);

const uint8_t RELAY_PIN=D1;
const bool RELAY_ACTIVE_LOW=true;
bool relayState=false, reported=false;

bool masterPower(bool on){
  relayState=on;
  digitalWrite(RELAY_PIN,(on^RELAY_ACTIVE_LOW)?HIGH:LOW);
  return true;
}

void setup(){
  Serial.begin(115200);
  pinMode(RELAY_PIN,OUTPUT);
  masterPower(false);
  WiFi.begin(SSID,PASSWORD);
  while(WiFi.status()!=WL_CONNECTED) delay(250);
  configTime(0,0,"pool.ntp.org","time.google.com");
  while(time(nullptr)<1700000000) delay(100);
#if OMNILINK_HTTP_TLS
  static BearSSL::X509List ca(ROOT_CA);
  network.setTrustAnchors(&ca); // verifies both the CA and the VPS hostname
#endif
  omniLink.onBool(0,masterPower); // Dashboard V0 controls this board's relay
  omniLink.begin(BASE_URL,DEVICE_ID,DEVICE_SECRET,"omnilink-esp8266-http-0.2");
}

void loop(){
  omniLink.loop();
  if(omniLink.connected()&&!reported){omniLink.reportBool(0,relayState);reported=true;}
  if(!omniLink.connected())reported=false;
  delay(2);
}
