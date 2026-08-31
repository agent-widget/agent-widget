#include "ota_events.h"

#include <stdarg.h>
#include <stdio.h>

#include "freertos/FreeRTOS.h"

static uint32_t s_seq = 0;
static uint32_t s_cmd_id = 0;
static portMUX_TYPE s_spinlock = portMUX_INITIALIZER_UNLOCKED;

void ota_evt(const char *event, const char *fmt, ...)
{
    taskENTER_CRITICAL(&s_spinlock);
    uint32_t seq = ++s_seq;
    taskEXIT_CRITICAL(&s_spinlock);

    printf("AW_EVT seq=%u event=%s ", (unsigned)seq, event);
    if (fmt != NULL && fmt[0] != '\0') {
        va_list ap;
        va_start(ap, fmt);
        vprintf(fmt, ap);
        va_end(ap);
    }
    printf("\n");
    fflush(stdout);
}

void ota_cmd_ack(uint32_t id, const char *result)
{
    printf("AW_CMD id=%u result=%s\n", (unsigned)id, result);
    fflush(stdout);
}

uint32_t ota_events_next_cmd_id(void)
{
    taskENTER_CRITICAL(&s_spinlock);
    uint32_t id = ++s_cmd_id;
    taskEXIT_CRITICAL(&s_spinlock);
    return id;
}
