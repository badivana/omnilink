/* OmniLink Arduino 0.3 - Arduino Uno / Nano over USB Serial, for OmniLink Server v0.6.

   The Uno has no network hardware: a computer runs the server's gateway, which
   talks to OmniLink. Paste the device ID and secret below; the gateway reads
   them from the board over USB when it starts. Upload, close Serial Monitor,
   then either set OMNILINK_SERIAL_GATEWAY=COM4 in the server's .env (run.bat
   then opens the gateway in its own window) or run in the server folder:
     .venv\Scripts\python examples\arduino_uno_serial_gateway.py --serial COM4 --url https://iot.example.com

   Matches the demo device made by the server:  python -m examples.create_demo
   (in a fresh account it allocates the pins below; otherwise copy the numbers
   shown under Devices & pins):
     V0 Power            BOOL    writable   switches the selected output
     V1 Output selection UINT8   writable   0 = output A, 1 = output B
     V2 Setpoint         UINT32  writable   measurement interval, 1..300 s
     V3 Measurement      FLOAT32 read-only  A0 input, 0..100 %
   Do not use Serial.print for debugging: the USB port carries the OmniLink protocol. */
#include <OmniLink.h>

// ===================== [CHANGE] Device credentials =====================
// Paste the ID and secret shown when you created the device in OmniLink
// (Devices & pins -> + Device). Anyone with USB access to the board can read them.
const char DEVICE_ID[]     = "";   // e.g. "dev_0123456789abcdef0123"
const char DEVICE_SECRET[] = "";   // 64 hex characters
// =======================================================================

const uint16_t PIN_POWER = 0, PIN_OUTPUT = 1, PIN_SETPOINT = 2, PIN_MEASUREMENT = 3;
const uint8_t OUTPUT_A = 7, OUTPUT_B = 8;   // relay/LED pins
const bool OUTPUT_ACTIVE_LOW = true;        // most relay modules
const bool MEASUREMENT_ENABLED = true;      // false if nothing is wired to A0

OmniLink link(Serial);
bool power = false; uint32_t outputSel = 0, intervalS = 10; uint32_t lastSample = 0;

void applyOutputs() {
  digitalWrite(OUTPUT_A, ((power && outputSel == 0) ^ OUTPUT_ACTIVE_LOW) ? HIGH : LOW);
  digitalWrite(OUTPUT_B, ((power && outputSel == 1) ^ OUTPUT_ACTIVE_LOW) ? HIGH : LOW);
}
bool setPower(bool on) { power = on; applyOutputs(); return true; }
bool setOutput(uint32_t v) { if (v > 1) return false; outputSel = v; applyOutputs(); return true; }
bool setInterval(uint32_t s) { if (s < 1 || s > 300) return false; intervalS = s; return true; }

void sampleMeasurement() {
  if (!MEASUREMENT_ENABLED) return;
  float percent = analogRead(A0) * 100.0f / 1023.0f;
  link.reportFloat(PIN_MEASUREMENT, percent);
  link.telemetryFloat("measurement", percent);
}
// The gateway sends "sync" whenever it (re)connects to the server.
void reportState() {
  link.reportBool(PIN_POWER, power);
  link.reportUInt(PIN_OUTPUT, omnilink::T_UINT8, outputSel);
  link.reportUInt(PIN_SETPOINT, omnilink::T_UINT32, intervalS);
  sampleMeasurement();
}

void setup() {
  Serial.begin(115200);
  pinMode(OUTPUT_A, OUTPUT); pinMode(OUTPUT_B, OUTPUT); applyOutputs();
  link.onBool(PIN_POWER, setPower);
  link.onUInt(PIN_OUTPUT, setOutput);
  link.onUInt(PIN_SETPOINT, setInterval);
  link.onSync(reportState);
  link.begin(DEVICE_ID, DEVICE_SECRET);
}

void loop() {
  link.loop();
  if (millis() - lastSample >= intervalS * 1000UL) { lastSample = millis(); sampleMeasurement(); }
}
