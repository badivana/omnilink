# OmniLink widgets: Blynk-style setup and firmware recipes

This guide takes each dashboard widget from a real job to the channel settings and device code needed to make it work. Widgets send or display **OmniLink virtual channels**. The device firmware maps those channels to the pins and actions on that board.

## The repeatable setup

1. Create a device in OmniLink and add its channels under **Devices & pins**. Select the data type and writable/read-only setting.
2. Add a dashboard widget, choose that device and its channel, then set the widget values, labels, units, and safe limits.
3. In firmware, register a handler for that channel if it is writable. The handler controls the real output. Report readings and actual output states back to OmniLink.
4. Run the device, open the dashboard, and watch **Command activity**. “Applied” means the device acknowledged the action; a fresh report shows the value it says it applied.

The source snippets below use OmniLink Arduino library 0.2. ESP32 and ESP8266 can connect with HTTP/HTTPS or MQTT. Uno/Nano uses `OmniLinkSerial` plus the HTTPS gateway shipped with the server. Each command callback returns `true` after applying the command or `false` to reject it. More setup is in the library README.

## Controls

| Widget | Typical job | Configure the channel | Firmware action |
|---|---|---|---|
| Switch | Keep a relay, pump, light, or enable state ON/OFF | Writable BOOL; set On=true and Off=false (or matching numeric values) | `link.onBool(0, setRelay);` then report the actual state with `reportBool(0, state)`. |
| Button | Send a one-time request such as reset, sample now, or pulse | Writable BOOL/UINT; set the value the firmware expects | Register a callback that performs the action. For a pulse, use a timer in the sketch to turn the output back off. |
| Slider | Set brightness, speed, threshold, or target | Writable numeric type; channel min/max must cover the widget range | Register `onUInt` or `onInt`; map the value to the actuator. Keep limits safe. |
| Selector | Choose a mode such as AUTO/MANUAL or LOW/MEDIUM/HIGH | Writable UINT or STRING; each option value must match the channel type | Register an integer/string callback and switch device behavior on that value. |
| Value input | Send a typed setpoint or text command | Writable channel of matching type; configure bounds for numeric channels | Use the matching typed callback and validate again in firmware before acting. |
| Joystick | Send X/Y for a robot, pan/tilt head, or two-axis control | Two writable numeric channels on the same device, e.g. V10 and V11 | Register one handler per axis. Convert each range to motor/servo units and stop on neutral/release as required. |
| Colour picker | Set RGB colour for an LED controller | Writable STRING channel | Parse `#RRGGBB` in firmware and write the colour through the LED driver. |
| Value stepper | Nudge a setpoint up/down | Writable numeric channel with min/max and step | Accept each new value and apply bounds before updating hardware. |
| Schedule controls | Set repeating or clock-based actions | Select a writable channel; schedule values must match its type | Keep a device handler for that channel. The server sends schedule commands while the browser is closed; the device must be online to apply them. |

### Switch to a relay (ESP32/ESP8266)

Create writable BOOL V0 named `Pump power`. In the widget choose V0, On=`true`, Off=`false`. The GPIO mapping belongs in the sketch:

```cpp
const int RELAY_PIN = 17;              // use a GPIO valid for your board
const bool ACTIVE_LOW = true;
bool pumpOn = false;

bool setPump(bool on) {
  pumpOn = on;
  digitalWrite(RELAY_PIN, (on ^ ACTIVE_LOW) ? HIGH : LOW);
  return true;
}

void setup() {
  pinMode(RELAY_PIN, OUTPUT);
  setPump(false);
  link.onBool(0, setPump);             // virtual V0 -> relay action
}
// After connecting, report the initial/applied state:
// link.reportBool(0, pumpOn);
```

### Slider to PWM brightness

Create writable UINT16 V1 with minimum 0 and maximum 255. Set the slider range to 0–255 and step 1. Map the virtual value to a board-supported PWM output:

```cpp
bool setBrightness(uint32_t value) {
  value = constrain(value, 0, 255);
  analogWrite(LED_PIN, value);         // check PWM API and pin for your board
  link.reportUInt(1, 5, value);        // type 5 is UINT16
  return true;
}
link.onUInt(1, setBrightness);
```

### Selector for operating mode

Create writable UINT8 V2. Configure options `0 = AUTO`, `1 = MANUAL`, `2 = SERVICE`:

```cpp
bool setMode(uint32_t mode) {
  if (mode > 2) return false;
  controllerMode = mode;
  applyMode();
  link.reportUInt(2, 3, mode);         // type 3 is UINT8
  return true;
}
link.onUInt(2, setMode);
```

The widget sends the configured option value. Make the firmware's mode numbers match exactly.

### Button for a timed pulse

Create writable BOOL V3 and configure the button to send `true`. Keep the pulse non-blocking so MQTT and device control continue running:

```cpp
bool triggerPulse(bool requested) {
  if (!requested) return true;
  digitalWrite(PULSE_PIN, HIGH);
  pulseEndsAt = millis() + 300;
  return true;
}
link.onBool(3, triggerPulse);

void loop() {
  link.loop();
  if (pulseEndsAt && int32_t(millis() - pulseEndsAt) >= 0) {
    digitalWrite(PULSE_PIN, LOW);
    pulseEndsAt = 0;
  }
}
```

The current Arduino library remembers duplicate commands only in RAM. After a device restart, a still-pending one-shot command can run again. Prefer idempotent state changes such as “set relay ON”; avoid using a pulse/trigger widget for hazardous one-shot actions with this initial library release.

### Joystick for two servos

Create writable INT16 V10 and V11 with a range such as -100 to 100. Choose both pins in the joystick and configure the same range. `onInt` is used here because the signed values include negatives:

```cpp
bool setPan(int32_t x)  { panServo.write(map(constrain(x,-100,100),-100,100,0,180)); return true; }
bool setTilt(int32_t y) { tiltServo.write(map(constrain(y,-100,100),-100,100,0,180)); return true; }
link.onInt(10, setPan);
link.onInt(11, setTilt);
```

### Colour picker for an RGB strip

Create writable STRING V12. The widget sends strings such as `#33AAFF`; parse them and pass RGB values to the LED library:

```cpp
bool setColour(const char *hex) {
  unsigned int rgb;
  if (sscanf(hex, "#%06x", &rgb) != 1) return false;
  setRgb((rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255);
  return true;
}
link.onString(12, setColour);
```

## Read-only and analysis widgets

| Widget | Use it for | Channel/data setup | Device code |
|---|---|---|---|
| LED indicator | Show a discrete state such as relay active, door open, or alarm | Read-only BOOL/UINT pin; configure the exact “lit” value | Publish actual state with `reportBool` or `reportUInt` whenever it changes. |
| Value display | Show a sensor, setpoint, desired value, or metric | Select device, channel/metric, reported/desired/telemetry source, and precision | Report the measured value, or call a telemetry helper for history. |
| Gauge / progress bar | Show a bounded measurement such as temperature, level, or percent | Numeric pin/metric and realistic min/max/unit | Send a numeric report or telemetry sample; choose display bounds independently from hardware safety bounds. |
| Chart | Compare a sensor over time or compare multiple devices | Choose telemetry metrics, time window, and line/bar/point/state style | Example: `link.telemetryFloat("temperature", celsius);` after a real sensor measurement. |
| Device status | Check online state and last contact | Select device; no pin required | No widget code. Device must publish heartbeat/status or make accepted server requests. |
| Device table | Inspect several current channel readings | Select device; add channels first | Report each channel's current state. |
| Map | Show coordinates | Provide latitude and longitude numeric pins (or location data as configured) | Report actual coordinates; map tiles are a separate display setting. |
| Floor plan / process view | Place live readings over a room or equipment diagram | Upload a background, place markers, bind each marker to a channel | Report each underlying channel; the image is only the dashboard layout. |
| Navigation | Move between dashboards | Select an existing destination dashboard | No device code. |
| Text card | Add labels or instructions | Enter static text | No device code. |

### Temperature value plus historical chart

Create read-only FLOAT32 V20 named `Water temperature`. For the chart, select telemetry metric `temperature`; the channel widget can show the latest reported value, and telemetry is stored for history:

```cpp
float celsius = readTemperatureSensor();
link.reportFloat(20, celsius);              // latest channel value
link.telemetryFloat("temperature", celsius); // historical chart series
```

Call these only when the sensor produced a valid reading. Choose a sample interval that suits the sensor and data-retention needs.

## Browser input widgets

Location, motion/orientation, camera, microphone, BLE reader, and browser serial widgets use browser APIs. They ask for local permission and their readings stay in that browser session. They do not automatically write OmniLink channels or reach Arduino hardware. To send a browser reading to a device/server, build an explicit authenticated integration for that purpose.

## Troubleshooting a widget that does not work

1. Confirm the selected device is online and the channel is allocated to that device.
2. Verify widget type, channel data type, writable flag, min/max, and selector values agree with the firmware.
3. Check **Command activity**. `rejected` usually means type/value/expiry mismatch; no command can mean the widget is read-only or bound to the wrong pin.
4. A command marked `applied` only records the device's acknowledgment. Verify the physical output and report the actual state back.
5. For ESP MQTT, check server hostname, port 8883, device credentials, CA certificate, NTP time, Wi-Fi, and broker provisioning status.
6. For Uno serial, keep the USB host and gateway process running and close Arduino Serial Monitor before opening the COM port in the gateway.
