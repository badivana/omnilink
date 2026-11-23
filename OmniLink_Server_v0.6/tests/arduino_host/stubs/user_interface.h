#pragma once
#include <esp_system.h>
inline uint32_t os_random() { return esp_random(); }
