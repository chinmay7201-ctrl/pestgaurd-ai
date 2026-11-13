// PestGuard sensor node: potentiometer = piezo sensor signal after bandpass filter
const int SENSOR = A0, LED = 13, BUZZER = 8;
const int THRESHOLD = 600;      // level that means pest chewing
int hits = 0;

void setup() {
  Serial.begin(9600);
  pinMode(LED, OUTPUT);
  pinMode(BUZZER, OUTPUT);
  Serial.println("PestGuard node-1 | Zone A started");
}

void loop() {
  int level = analogRead(SENSOR);              // 0 to 1023
  hits = (level > THRESHOLD) ? hits + 1 : 0;
  bool pest = hits >= 3;                       // 3 readings in a row = confirmed

  digitalWrite(LED, pest);
  if (pest) tone(BUZZER, 1000); else noTone(BUZZER);

  Serial.print("Vibration level: ");
  Serial.print(level);
  Serial.println(pest ? "  -> PEST DETECTED in Zone A" : "  -> Healthy");
  delay(500);
}
