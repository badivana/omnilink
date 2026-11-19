#include <OmniLink.h>

/* Connect the Uno's USB cable to a computer running the supplied gateway.
   The gateway owns the device secret and forwards these JSON lines over HTTPS. */
const uint8_t RELAY_PIN=7;const bool RELAY_ACTIVE_LOW=true;bool relayState=false;
OmniLink link(Serial);
bool setRelay(bool on){relayState=on;digitalWrite(RELAY_PIN,(on^RELAY_ACTIVE_LOW)?HIGH:LOW);return true;}
void setup(){Serial.begin(115200);link.begin();pinMode(RELAY_PIN,OUTPUT);setRelay(false);link.onBool(0,setRelay);link.reportBool(0,relayState);}
void loop(){link.loop();}
