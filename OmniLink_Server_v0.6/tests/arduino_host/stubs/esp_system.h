#pragma once
#include <Arduino.h>
inline uint32_t esp_random() { static std::mt19937 g{std::random_device{}()}; return g(); }
inline void esp_fill_random(void *buf, size_t n) { uint8_t *b = (uint8_t *)buf; for (size_t i = 0; i < n; i++) b[i] = uint8_t(esp_random()); }
