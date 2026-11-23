// Runs an Arduino sketch on the host: setup() once, then loop() until stdin closes.
void setup();
void loop();
int main() { setup(); for (;;) loop(); }
