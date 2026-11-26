"""Host regression check: python -B tests/hardware/check_cage_node.py.

Compiles actual probe functions and the R15 bridge with transport/GPIO mocks.
Uses an existing g++ or clang++; all build files are temporary and removed.
This checks protocol decisions, not ESP32 compilation, electrical timing or hardware.
Optional --r15-archive couples the actual request bridge to the frozen Pico C
sequencer through its supplied host interface, using idealized external pins.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import zipfile


MOCKS = r"""
#include <array>
#include <cassert>
#include <cmath>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <deque>
#include <string>
#include <vector>

struct SerialMock {
  std::string text;
  void printf(const char *format, ...) {
    char line[256]; va_list args; va_start(args, format);
    vsnprintf(line, sizeof(line), format, args); va_end(args); text += line;
  }
} Serial;

struct OneWire {
  std::deque<int> presence{1, 1, 1}, bits{1, 0, 1};
  std::vector<uint8_t> commands;
  std::vector<std::array<uint8_t, 8>> devices;
  std::array<uint8_t, 9> scratch{};
  size_t searchIndex = 0, readIndex = 0;
  unsigned reads = 0, selections = 0;
  static uint8_t crc8(const uint8_t *data, uint8_t length) {
    uint8_t crc = 0;
    while (length--) {
      uint8_t byte = *data++;
      for (unsigned bit = 0; bit < 8; ++bit) {
        uint8_t mix = (crc ^ byte) & 1;
        crc >>= 1; if (mix) crc ^= 0x8C; byte >>= 1;
      }
    }
    return crc;
  }
  explicit OneWire(int16_t temperature = 25 * 16) {
    scratch = {uint8_t(temperature & 255), uint8_t(uint16_t(temperature) >> 8),
               75, 70, 0x7F, 0xFF, 12, 16, 0};
    scratch[8] = crc8(scratch.data(), 8);
  }
  int reset() {
    assert(!presence.empty()); int result = presence.front(); presence.pop_front(); return result;
  }
  int read_bit() {
    assert(!bits.empty()); int result = bits.front(); bits.pop_front(); return result;
  }
  void select(const uint8_t *) { ++selections; }
  void write(uint8_t command, uint8_t = 0) {
    commands.push_back(command); if (command == 0xBE) readIndex = 0;
  }
  uint8_t read() { ++reads; return scratch.at(readIndex++); }
  void reset_search() { searchIndex = 0; }
  bool search(uint8_t *rom) {
    if (searchIndex == devices.size()) return false;
    memcpy(rom, devices[searchIndex++].data(), 8); return true;
  }
};
"""

CHECKS = r"""
std::array<uint8_t, 8> address(uint8_t serial) {
  std::array<uint8_t, 8> rom{0x28, serial, 2, 3, 4, 5, 6, 0};
  rom[7] = OneWire::crc8(rom.data(), 7); return rom;
}

int main() {
  check_bridge();
  check_bridge_gpio();
  check_bridge_hello();
  check_sensor_logging();
  const auto rom = address(1); unsigned checks = 0;
  const char *diagnostic = nullptr;
  {
    OneWire bus; bool started = startProbe(bus, rom.data(), true, &diagnostic);
    assert(!strcmp(diagnostic, "converting"));
    assert(started && readProbe(bus, rom.data(), started, &diagnostic) == 25.0f && !started);
    assert(!strcmp(diagnostic, "ok"));
    assert((bus.commands == std::vector<uint8_t>{0xB4, 0x44, 0xBE}));
    assert(bus.reads == 9 && bus.selections == 3);
    assert(std::isnan(readProbe(bus, rom.data(), started)) && bus.reads == 9); ++checks;
  }
  {
    // Previously: failed Convert T reset could publish this valid old scratchpad.
    OneWire bus; bus.presence = {0}; bus.bits.clear();
    bool started = startProbe(bus, rom.data(), true, &diagnostic);
    assert(!started && std::isnan(readProbe(bus, rom.data(), started, &diagnostic)));
    assert(!strcmp(diagnostic, "lost_before_power_check"));
    assert(bus.commands.empty() && bus.reads == 0); ++checks;
  }
  {
    OneWire bus; bus.presence.clear(); bus.bits.clear();
    diagnostic = "not_detected";
    bool started = startProbe(bus, rom.data(), false, &diagnostic);
    assert(!started && std::isnan(readProbe(bus, rom.data(), started, &diagnostic)));
    assert(!strcmp(diagnostic, "not_detected"));
    assert(bus.commands.empty() && bus.reads == 0); ++checks;
  }
  {
    // Parasite power cannot use this polling protocol.
    OneWire bus; bus.presence = {1}; bus.bits = {0};
    bool started = startProbe(bus, rom.data(), true, &diagnostic);
    assert(!started && std::isnan(readProbe(bus, rom.data(), started, &diagnostic)));
    assert(!strcmp(diagnostic, "external_power_not_reported"));
    assert((bus.commands == std::vector<uint8_t>{0xB4}) && bus.reads == 0); ++checks;
  }
  {
    OneWire bus; bus.presence = {1, 0}; bus.bits = {1};
    bool started = startProbe(bus, rom.data(), true, &diagnostic);
    assert(!started && std::isnan(readProbe(bus, rom.data(), started, &diagnostic)) && bus.reads == 0);
    assert(!strcmp(diagnostic, "lost_before_conversion")); ++checks;
  }
  {
    // A released/disconnected bus reads high: no busy response means no new conversion.
    OneWire bus; bus.presence = {1, 1}; bus.bits = {1, 1};
    bool started = startProbe(bus, rom.data(), true, &diagnostic);
    assert(!started && std::isnan(readProbe(bus, rom.data(), started, &diagnostic)) && bus.reads == 0);
    assert(!strcmp(diagnostic, "conversion_not_started")); ++checks;
  }
  {
    OneWire bus; bus.presence = {1, 1}; bus.bits = {1, 0, 0};
    bool started = startProbe(bus, rom.data(), true, &diagnostic);
    assert(started && std::isnan(readProbe(bus, rom.data(), started, &diagnostic)) && !started);
    assert(!strcmp(diagnostic, "conversion_incomplete"));
    assert(bus.reads == 0); ++checks;
  }
  {
    OneWire bus; bus.presence = {1, 1, 0};
    bool started = startProbe(bus, rom.data(), true, &diagnostic);
    assert(started && std::isnan(readProbe(bus, rom.data(), started, &diagnostic)) && bus.reads == 0);
    assert(!strcmp(diagnostic, "lost_before_read")); ++checks;
  }
  {
    OneWire bus; bus.scratch[8] ^= 1;
    bool started = startProbe(bus, rom.data(), true);
    assert(std::isnan(readProbe(bus, rom.data(), started, &diagnostic)));
    assert(!strcmp(diagnostic, "scratchpad_crc_error")); ++checks;
  }
  {
    OneWire hot(85 * 16), cool(-10 * 16);
    bool hotStarted = startProbe(hot, rom.data(), true);
    bool coolStarted = startProbe(cool, rom.data(), true);
    assert(std::isnan(readProbe(hot, rom.data(), hotStarted, &diagnostic)));
    assert(!strcmp(diagnostic, "out_of_range"));
    assert(readProbe(cool, rom.data(), coolStarted, &diagnostic) == -10.0f);
    assert(!strcmp(diagnostic, "ok")); ++checks;
  }
  {
    // Validated ROM identity is reported once, changes reported without pinning.
    OneWire bus; uint8_t observed[8] = {}; bus.devices = {rom}; Serial.text.clear();
    assert(findProbe(bus, observed, "T2", 13));
    assert(Serial.text.find("probe channel=T2 gpio=13 rom=28") == 0);
    assert(Serial.text.find("event=found\n") != std::string::npos);
    auto first = Serial.text;
    assert(findProbe(bus, observed, "T2", 13) && Serial.text == first);
    bus.devices = {address(9)};
    assert(findProbe(bus, observed, "T2", 13));
    assert(Serial.text.find("event=changed\n") != std::string::npos);
    assert(memcmp(observed, address(9).data(), 8) == 0); ++checks;
  }
  {
    OneWire bus; uint8_t observed[8] = {}; Serial.text.clear();
    assert(!findProbe(bus, observed, "T3", 14, &diagnostic));
    assert(!strcmp(diagnostic, "not_detected"));
    auto invalid = rom; invalid[7] ^= 1; bus.devices = {invalid};
    assert(!findProbe(bus, observed, "T3", 14, &diagnostic));
    assert(!strcmp(diagnostic, "rom_crc_error"));
    invalid = rom; invalid[0] = 0x10; invalid[7] = OneWire::crc8(invalid.data(), 7);
    bus.devices = {invalid}; assert(!findProbe(bus, observed, "T3", 14, &diagnostic));
    assert(!strcmp(diagnostic, "unexpected_family"));
    bus.devices = {rom, address(9)}; assert(!findProbe(bus, observed, "T3", 14, &diagnostic));
    assert(!strcmp(diagnostic, "multiple_devices"));
    assert(Serial.text.empty() && observed[0] == 0);
    bus.devices = {rom}; assert(findProbe(bus, observed, "T3", 14, &diagnostic));
    assert(!strcmp(diagnostic, "found"));
    assert(Serial.text.find("probe channel=T3 gpio=14 rom=28") == 0); ++checks;
  }
  printf("PASS: %u host probe regression scenarios; no hardware validation\n", checks);
}
"""


BRIDGE_CHECKS = r"""
#include "r15_bridge.h"
const char *nonce = "11111111-1111-4111-8111-111111111111";
const char *other = "22222222-2222-4222-8222-222222222222";
constexpr uint64_t epoch = 1800000000000ULL;
r15::Command command(unsigned seq, r15::Action action=r15::Action::On,
                     unsigned zone=1, unsigned hold=3000) {
  r15::Command c; strcpy(c.session,nonce);
  snprintf(c.id,sizeof(c.id),"00000000-0000-4000-8000-%012u",seq);
  c.sequence=seq; c.action=action; c.zone=zone; c.hold_ms=hold;
  c.issued_ms=epoch; c.expires_ms=epoch+5000; return c;
}
void beat(r15::Bridge &b,unsigned seq=1,uint32_t now=0) {
  auto c=command(seq,r15::Action::Heartbeat,0,0);
  c.issued_ms=epoch+now; c.expires_ms=c.issued_ms+1000;
  auto r=b.receive(c,epoch+now,now,true,true); assert(!strcmp(r.status,"received"));
}
bool parse_frame(const std::string &s) {
  r15::Command c; return r15::parse(reinterpret_cast<const uint8_t *>(s.data()),s.size(),c);
}
void check_bridge() {
  unsigned checks=0;
  const std::string frame=std::string("R15/1 ")+nonce+" "+other+" 1 2 on 3000 1800000000000 1800000005000";
  assert(parse_frame(frame)); ++checks;
  for (const char *hold:{"1","3001","4000","4500","5000"}) {
    assert(parse_frame(std::string("R15/1 ")+nonce+" "+other+" 1 2 on "+hold+
                       " 1800000000000 1800000005000")); ++checks;
  }
  for (const auto &bad:std::vector<std::string>{"",frame+"\n",frame+" extra"," "+frame,
        frame+" ",std::string(257,'x'),
        "R15/1  11111111-1111-4111-8111-111111111111"}) {
    assert(!parse_frame(bad)); ++checks;
  }
  { auto bad=frame; bad[10]='\0'; assert(!parse_frame(bad)); ++checks; }
  for(const char *tail:{"0 1 on 10 1800000000000 1800000001000",
      "4294967296 1 on 10 1800000000000 1800000001000",
      "1 18446744073709551616 on 10 1800000000000 1800000001000",
      "1 0 on 10 1800000000000 1800000001000",
      "1 1 on 0 1800000000000 1800000001000",
      "1 1 on 5001 1800000000000 1800000001000",
      "1 1 on 4294967296 1800000000000 1800000001000",
      "1 1 off 1 1800000000000 1800000001000",
      "1 1 heartbeat 0 1800000000000 1800000001000",
      "1 0 stop 0 9007199254740992 1800000000000",
      "01 1 on 10 1800000000000 1800000001000"}) {
    assert(!parse_frame(std::string("R15/1 ")+nonce+" "+other+" "+tail)); ++checks;
  }
  {
    r15::Bridge b; b.connect(nonce); beat(b);
    auto r=b.receive(command(2),epoch,0,true,true);
    assert(!strcmp(r.reason,"outputs_locked") && b.requests()==0); ++checks;
  }
  {
    r15::Bridge b(true); b.connect(nonce); beat(b);
    auto c=command(2); auto r=b.receive(c,epoch,0,true,true);
    assert(!strcmp(r.status,"requested") && r.requested && b.requests()==1); ++checks;
    r=b.receive(c,epoch+900,900,true,true);
    assert(r.duplicate && b.requests()==1); // Does not extend heartbeat or request.
    b.tick(1000,true,true,true); assert(b.requests()==0 && !b.heartbeat()); ++checks;
    r15::Completion done; assert(b.completion(done) && !strcmp(done.reason,"gateway_lease_expired"));
    r=b.receive(c,epoch+1001,1001,true,true);
    assert(r.duplicate && !strcmp(r.status,"execution_unverified") && !r.requested); ++checks;
  }
  {
    // TTL limits receipt, not the admitted REQ duration. Renewed HB is still required.
    r15::Bridge b(true); b.connect(nonce); beat(b);
    auto c=command(2,r15::Action::On,1,5000); c.expires_ms=epoch+1;
    assert(b.receive(c,epoch,0,true,true).requested);
    for (unsigned t=500,s=3;t<5000;t+=500,++s) {
      beat(b,s,t); b.tick(t,true,true,true); assert(b.requests()==1);
    }
    auto duplicate=b.receive(c,epoch+4999,4999,true,true);
    assert(duplicate.duplicate && b.requests()==1);
    b.tick(5000,true,true,true); assert(!b.requests());
    r15::Completion done; assert(b.completion(done) && !strcmp(done.reason,"request_hold_finished"));
    duplicate=b.receive(c,epoch+5001,5001,true,true);
    assert(duplicate.duplicate && !duplicate.requested && !b.requests()); ++checks;
  }
  {
    r15::Bridge b(true); b.connect(nonce); beat(b); auto c=command(2);
    b.receive(c,epoch,0,true,true); c.hold_ms=100;
    auto r=b.receive(c,epoch,0,true,true);
    assert(!strcmp(r.reason,"command_id_conflict") && b.requests()==1); ++checks;
  }
  {
    r15::Bridge b(true); b.connect(nonce); beat(b);
    b.receive(command(2),epoch,0,true,true);
    auto second=b.receive(command(3,r15::Action::On,2),epoch,0,true,true);
    assert(!strcmp(second.reason,"bridge_busy") && b.requests()==1); ++checks;
    auto off=command(4,r15::Action::Off,2,0); b.receive(off,epoch,0,true,true);
    assert(b.requests()==1); ++checks;
    off=command(5,r15::Action::Off,1,0); b.receive(off,0,0,true,true);
    assert(b.requests()==0); ++checks;
  }
  {
    r15::Bridge b(true); b.connect(nonce); beat(b);
    auto c=command(2); b.receive(c,epoch,0,true,true);
    auto stop=command(1,r15::Action::Stop,0,0); // Old sequence, unknown UTC: still fail OFF.
    strcpy(stop.id,other);
    auto r=b.receive(stop,0,10,true,true);
    assert(!strcmp(r.status,"requested") && b.requests()==0 && b.latched()); ++checks;
    beat(b,3,100); b.tick(100,true,true,true); assert(!b.heartbeat());
    r=b.receive(command(4),epoch+100,100,true,true);
    assert(!strcmp(r.reason,"stop_latched")); ++checks;
  }
  {
    r15::Bridge b(true); b.connect(nonce); beat(b);
    auto stop=command(5,r15::Action::Stop,0,0); b.receive(stop,epoch,0,true,true);
    auto r=b.receive(command(2),epoch,0,true,true);
    assert(!strcmp(r.reason,"stale_sequence") && b.requests()==0); ++checks;
  }
  for (unsigned variant=0;variant<5;++variant) {
    r15::Bridge b(true); b.connect(nonce); beat(b); auto c=command(2);
    uint64_t now=epoch;
    if (variant==0) now=0;
    if (variant==1) c.expires_ms=epoch;
    if (variant==2) c.issued_ms=epoch+1;
    if (variant==3) c.expires_ms=epoch+5001;
    if (variant==4) strcpy(c.session,other);
    auto r=b.receive(c,now,0,true,true);
    assert(!strcmp(r.status,"rejected") && b.requests()==0); ++checks;
  }
  {
    r15::Bridge b(true); b.connect(nonce);
    auto r=b.receive(command(1),epoch,0,true,true);
    assert(!strcmp(r.reason,"gateway_lease_expired")); ++checks;
    beat(b,2);
    r=b.receive(command(3),epoch,0,false,true);
    assert(!strcmp(r.reason,"r15_status_pin_low")); ++checks;
    r=b.receive(command(4),epoch,0,true,false);
    assert(!strcmp(r.reason,"r15_status_pin_low")); ++checks;
  }
  for (unsigned variant=0;variant<3;++variant) {
    r15::Bridge b(true); b.connect(nonce); beat(b);
    b.receive(command(2),epoch,0,true,true);
    b.tick(20,variant!=0,variant!=1,variant!=2); assert(b.requests()==0); ++checks;
  }
  {
    r15::Bridge b(true); b.connect(nonce); beat(b); auto c=command(2);
    b.receive(c,epoch,0,true,true);
    for (unsigned t=500,s=3;t<=3000;t+=500,++s) { beat(b,s,t); b.tick(t,true,true,true); }
    assert(b.requests()==0); r15::Completion done; assert(b.completion(done));
    assert(!strcmp(done.reason,"request_hold_finished")); ++checks;
    auto later=command(10); later.issued_ms=epoch+3001; later.expires_ms=epoch+4001;
    assert(!strcmp(b.receive(later,epoch+3001,3001,true,true).reason,"bridge_recycle_wait")); ++checks;
    beat(b,11,7000); later=command(12,r15::Action::On,3,100);
    later.issued_ms=epoch+7000; later.expires_ms=epoch+8000;
    assert(!strcmp(b.receive(later,epoch+7000,7000,true,true).status,"requested") && b.requests()==4); ++checks;
  }
  {
    r15::Bridge b(true); b.connect(nonce); beat(b);
    auto c=command(2); b.receive(c,epoch,0,true,true); b.disconnect();
    assert(b.requests()==0 && !b.heartbeat());
    b.connect(other); assert(!strcmp(b.receive(c,epoch,0,true,true).reason,"session_mismatch")); ++checks;
  }
  {
    r15::Bridge b(true); b.connect(nonce);
    auto c=command(1,r15::Action::Heartbeat,0,0); c.expires_ms=epoch+5000;
    assert(!strcmp(b.receive(c,epoch+1000,0,true,true).reason,"heartbeat_stale")); ++checks;
    c=command(2,r15::Action::Heartbeat,0,0); c.expires_ms=epoch+100;
    b.receive(c,epoch,0,true,true); b.tick(100,true,true,true);
    assert(!b.lease(100)); ++checks;
  }
  {
    r15::Bridge b(true); b.connect(nonce);
    constexpr uint32_t near=UINT32_MAX-50;
    auto hb=command(1,r15::Action::Heartbeat,0,0); hb.expires_ms=epoch+1000;
    b.receive(hb,epoch,near,true,true);
    auto c=command(2,r15::Action::On,1,100); b.receive(c,epoch,near,true,true);
    b.tick(49,true,true,true); assert(b.requests()==0); ++checks;
  }
  {
    // Raw status HIGH is accepted only as an inhibit check, never physical confirmation.
    r15::Bridge b(true); b.connect(nonce); beat(b);
    auto r=b.receive(command(2),epoch,0,true,true);
    assert(!strcmp(r.reason,"physical_execution_unverified")); ++checks;
  }
  {
    r15::Bridge b(true); b.connect(nonce);
    auto hb=command(1,r15::Action::Heartbeat,0,0); hb.expires_ms=epoch+1000;
    b.receive(hb,epoch,0,true,true);
    auto duplicate=b.receive(hb,epoch+900,900,true,true);
    assert(duplicate.duplicate && !b.lease(1000)); ++checks;
    hb.sequence=2; hb.issued_ms+=500; hb.expires_ms+=500;
    auto changed=b.receive(hb,epoch+500,500,true,true);
    assert(!strcmp(changed.reason,"command_id_conflict") && !b.lease(1000)); ++checks;
  }
  {
    r15::Bridge b(true); b.connect(nonce); beat(b);
    b.receive(command(2),epoch,0,true,true); b.disconnect(); b.connect(other);
    auto hb=command(1,r15::Action::Heartbeat,0,0); strcpy(hb.session,other);
    b.receive(hb,epoch+20,20,true,true);
    auto next=command(2); strcpy(next.session,other);
    assert(!strcmp(b.receive(next,epoch+20,20,true,true).reason,"bridge_recycle_wait")); ++checks;
  }
  printf("PASS: %u R15 host protocol/safety scenarios; physical execution unverified\n",checks);
}
"""


GPIO_MOCKS = r"""
using TickType_t=uint32_t;
using gpio_num_t=unsigned;
constexpr int HIGH=1,LOW=0;
int r15Mux=0; bool r15Network=true;
r15::Bridge r15Bridge(true);
constexpr unsigned r15ReqPins[]={25,32,23};
constexpr unsigned r15HbPin=26,r15ArmedPin=19,r15LevelPin=33;
uint32_t gpioNow=0,gpioEnd=1600;
int pins[40]{};
struct Write { uint32_t at; unsigned pin; int value; };
std::vector<Write> gpioWrites;
bool stopAt600=false;
bool critical=false;
#define portENTER_CRITICAL(mux) do { (void)(mux); assert(!critical); critical=true; } while(0)
#define portEXIT_CRITICAL(mux) do { (void)(mux); assert(critical); critical=false; } while(0)
uint32_t millis() { return gpioNow; }
TickType_t xTaskGetTickCount() { return gpioNow; }
TickType_t pdMS_TO_TICKS(uint32_t ms) { return ms; }
int digitalRead(unsigned pin) { return pins[pin]; }
void gpio_set_level(gpio_num_t pin,int value) {
  assert(critical); // A concurrent STOP cannot slip between snapshot and GPIO write.
  pins[pin]=value; gpioWrites.push_back({gpioNow,pin,value});
  assert((pins[25]?1:0)+(pins[32]?1:0)+(pins[23]?1:0)<=1);
}
void vTaskDelayUntil(TickType_t *wake,TickType_t interval) {
  *wake+=interval; gpioNow=*wake;
  if (gpioNow==500) beat(r15Bridge,3,500);
  if (gpioNow==600 && stopAt600) {
    r15Bridge.receive(command(4,r15::Action::Stop,0,0),0,600,true,true);
    r15Bridge.receive(command(2),epoch+600,600,true,true); // Late duplicate cannot reactivate.
  }
  if (gpioNow>=gpioEnd) throw 1;
}
"""


GPIO_CHECKS = r"""
void check_bridge_gpio() {
  for (bool stop:{false,true}) {
    r15Bridge=r15::Bridge(true); r15Bridge.connect(nonce); beat(r15Bridge);
    memset(pins,0,sizeof(pins)); pins[19]=pins[33]=HIGH;
    gpioNow=0; gpioEnd=1600; stopAt600=stop; gpioWrites.clear();
    r15Bridge.receive(command(2),epoch,0,true,true);
    try { r15SafetyTask(nullptr); } catch(int) {}
    unsigned highCount=0; uint32_t dropped=0;
    for (const auto &w:gpioWrites) if(w.pin==25) {
      if(w.value==HIGH) ++highCount;
      else if(w.at) dropped=w.at;
    }
    assert(highCount==1); // Stable request has no forced LOW/HIGH glitches per tick.
    assert(dropped==(stop?600u:1500u)); // Timer runs while main-loop networking is absent.
    assert(!pins[25] && !pins[32] && !pins[23] && !pins[26]);
  }
  printf("PASS: 2 actual GPIO-task scheduling scenarios; simulated clocks/pins only\n");
}
"""

SENSOR_DIAGNOSTIC_MOCKS = r"""
int gpio_get_level(gpio_num_t pin) { return pins[pin]; }
struct DiagnosticWire {
  std::vector<uint8_t> addresses;
  std::deque<uint8_t> responses{2, 0, 5, 2};
  void beginTransmission(uint8_t address) { addresses.push_back(address); }
  uint8_t endTransmission() {
    assert(!responses.empty()); auto response = responses.front();
    responses.pop_front(); return response;
  }
} Wire;
"""

SENSOR_DIAGNOSTIC_CHECKS = r"""
void check_sensor_logging() {
  Serial.text.clear(); gpioNow = 0;
  pins[shtSdaPin] = 1; pins[shtSclPin] = 1; pins[hotPin] = 0; pins[coolPin] = 1;
  const auto writes = gpioWrites.size();
  logSensorDiagnostics("init_failed", "not_detected", "ok");
  assert((Wire.addresses == std::vector<uint8_t>{0x44, 0x45}));
  assert(Serial.text == "SENSOR sda=1 scl=1 dq_t2=0 dq_t3=1 i2c44=2 i2c45=0 sht=init_failed T2=not_detected T3=ok\n");
  const auto first = Serial.text;
  gpioNow = 29999; logSensorDiagnostics("ok", "ok", "ok");
  assert(Serial.text == first && Wire.addresses.size() == 2);
  gpioNow = 30000; logSensorDiagnostics("read_failed", "rom_crc_error", "multiple_devices");
  assert((Wire.addresses == std::vector<uint8_t>{0x44, 0x45, 0x44, 0x45}));
  assert(Serial.text.find("i2c44=5 i2c45=2 sht=read_failed T2=rom_crc_error T3=multiple_devices") != std::string::npos);
  assert(gpioWrites.size() == writes);
  printf("PASS: serial sensor diagnostics, bounded address probes and 30s rate limit\n");
}
"""


HELLO_MOCKS = r"""
#define HABITAT_R15_REQUEST_OUTPUTS 0
uint64_t r15UtcMs() { return epoch; }
void check_bridge_hello() {
  char session[37],active[37]={}; strcpy(session,nonce);
  const char *r15CommandTopic="fixture/r15/command/session";
  bool lease=false,stopped=false,hb=false; uint8_t mask=0;
"""

HELLO_CHECKS = r"""
  assert(size>0 && size<int(sizeof(payload)));
  assert(strstr(payload,"\"max_request_hold_ms\":5000,"));
  assert(strstr(payload,"\"outputs_locked\":true,"));
  assert(strstr(payload,"\"execution_status\":\"unverified\",\"actual_state\":null"));
  printf("PASS: actual locked Hello serializer advertises REQ 5000ms; no physical ACK\n");
}
"""


PICO_CHECKS = r"""
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include "r15_bridge.h"
extern "C" {
#include "sequencer.h"
void bridge_init_mode(unsigned enabled);
uint32_t bridge_tick(uint32_t bits,uint32_t now);
unsigned bridge_phase(void);
}

constexpr uint64_t epoch=1800000000000ULL;
constexpr const char *nonce="11111111-1111-4111-8111-111111111111";
// Test fixture only: sampled REQ/HB lines every 20ms, native Pico tick every
// 1ms. ARM feedback follows the second pulse; WINDOW is an ideal 5000ms pulse
// after a selectable integer-ms delay from TRIG. This does not simulate discrete
// gates, analog timing, task jitter or physical flow.
struct Rig {
  r15::Bridge esp;
  uint32_t now=0, seq=0, outputs=0, window_start=0;
  unsigned arm_edges=0, pump_ms=0, longest_run=0, run_length=0;
  unsigned valve_ms=0, trigger_count=0, first_run=0, run_end=0;
  unsigned request_on=0, request_off=0, preopen_at=0, trigger_at=0;
  unsigned request_rises=0, window_delay=1;
  uint8_t wire_req=0;
  bool wire_hb=false, armed=false, network=true, renew=true, level=true;
  bool leak=true, wd=true, por=true, health=true, last_arm=false;
  bool respond_window=true, cut_window=false, stuck_req=false, freeze_hb=false;
  bool commissioned;

  explicit Rig(bool pico_enabled=true,bool esp_enabled=true):
      esp(esp_enabled),commissioned(pico_enabled) {
    bridge_init_mode(pico_enabled?1u:0u); // In-memory test override, never firmware configuration.
    esp.connect(nonce);
    assert(!strcmp(send(make("heartbeat",0,0,1000)).status,"received"));
  }
  r15::Command make(const char *action,unsigned zone=1,unsigned hold=3000,unsigned ttl=5000) {
    char text[257]; ++seq;
    int size=snprintf(text,sizeof(text),"R15/1 %s aaaaaaaa-aaaa-4aaa-8aaa-%012u %u %u %s %u %llu %llu",
      nonce,seq,seq,zone,action,hold,
      static_cast<unsigned long long>(epoch+now),
      static_cast<unsigned long long>(epoch+now+ttl));
    assert(size>0 && static_cast<size_t>(size)<sizeof(text));
    r15::Command command;
    assert(r15::parse(reinterpret_cast<const uint8_t *>(text),static_cast<size_t>(size),command));
    return command;
  }
  r15::Result send(const r15::Command &command) {
    return esp.receive(command,epoch+now,now,armed,level);
  }
  bool pump() const { return outputs&(1u<<12); }
  void advance(uint32_t until) {
    assert(until>=now);
    while (now<until) {
      ++now;
      if (renew && network && now%500==0)
        assert(!strcmp(send(make("heartbeat",0,0,1000)).status,"received"));
      if (now%20==0) {
        esp.tick(now,network,armed,level);
        const auto previous_request=wire_req;
        wire_req=esp.requests();
        if (!previous_request && wire_req) { request_on=now; ++request_rises; }
        if (previous_request && !wire_req) request_off=now;
        if (!freeze_hb) wire_hb=esp.heartbeat();
      }
      const uint8_t request=stuck_req?1:wire_req;
      const bool window=window_start && now>=window_start && now-window_start<5000 && !cut_window;
      const bool button_released=now<300 || now>=340;
      const uint32_t inputs=request | (uint32_t(wire_hb)<<3) | (uint32_t(level)<<4) |
        (uint32_t(leak)<<5) | (uint32_t(wd)<<6) | (uint32_t(window)<<7) |
        (uint32_t(por)<<8) | (uint32_t(button_released)<<9) |
        (uint32_t(armed)<<10) | (uint32_t(health)<<19);
      const bool was_pump=pump();
      outputs=bridge_tick(inputs,now);
      if (!preopen_at && bridge_phase()==S_PREOPEN) preopen_at=now;
      const unsigned valves=(outputs>>13)&7u;
      assert(!valves || !(valves&(valves-1))); // Native sequencer stays one-hot.
      if (pump()) {
        assert(valves && window && level && leak && wd && por && armed && health);
        if (!was_pump) { assert(!first_run); first_run=now; }
        ++pump_ms; ++run_length;
        if (run_length>longest_run) longest_run=run_length;
        assert(run_length<=3000);
      } else {
        if (was_pump) run_end=now;
        run_length=0;
      }
      if (valves) ++valve_ms;
      if (outputs&(1u<<16)) {
        ++trigger_count;
        trigger_at=now;
        if (respond_window) window_start=now+window_delay;
      }
      const bool arm=outputs&(1u<<17);
      if (arm && !last_arm && ++arm_edges==2) armed=true;
      last_arm=arm;
      if (outputs&(1u<<18)) { armed=false; arm_edges=0; }
      if (!commissioned) assert(!(outputs & ((1u<<12)|(7u<<13)|(1u<<16))));
    }
  }
  void ready() {
    advance(400);
    assert(armed && bridge_phase()==S_IDLE && esp.lease(now));
  }
  r15::Command start(unsigned hold=3000,unsigned zone=1) {
    auto command=make("on",zone,hold);
    auto result=send(command);
    assert(result.requested && !strcmp(result.status,"requested"));
    assert(!strcmp(result.reason,"physical_execution_unverified"));
    return command;
  }
  void running(unsigned hold=5000) { ready(); start(hold); advance(1600); assert(pump()); }
  void no_resume(uint32_t until) {
    const auto before=pump_ms;
    advance(until);
    assert(!pump() && !esp.requests() && pump_ms==before);
  }
};

int main() {
  unsigned cases=0;
  { // Frozen main.c factory BENCH0 is represented by the supplied host override.
    Rig r(false); r.ready(); r.start(); r.advance(8000);
    assert(!r.pump_ms && !r.valve_ms && !r.trigger_count); ++cases;
  }
  {
    Rig r(true,false); r.ready();
    assert(!strcmp(r.send(r.make("on")).reason,"outputs_locked"));
    r.advance(8000); assert(!r.pump_ms && !r.valve_ms); ++cases;
  }
  for (unsigned hold:{1000u,2000u,3000u}) {
    Rig r; r.ready(); auto on=r.start(hold,hold/1000); r.advance(900);
    assert(r.send(on).duplicate); // Retransmission cannot extend the hold.
    r.advance(400+hold+20); assert(!r.esp.requests() && !r.pump());
    assert(r.pump_ms<hold && (hold==1000 ? r.pump_ms==0 : r.pump_ms>0));
    assert(!strcmp(r.send(r.make("on")).reason,"bridge_recycle_wait"));
    r.advance(8000); assert(bridge_phase()==S_IDLE);
    printf("TRACE: command_at_ms=400 request_hold_ms=%u req_high_ms=%u req_low_ms=%u preopen_ms=%u "
      "trigger_ms=%u window_high_ms=%u first_run_ms=%u run_end_ms=%u virtual_pico_run_ms=%u; not physical flow\n",
      hold,r.request_on,r.request_off,r.preopen_at,r.trigger_at,r.window_start,r.first_run,r.run_end,r.pump_ms);
    ++cases;
  }
  // The unchanged native sequencer is the forward oracle. Sweep receipt phases
  // relative to the ESP task; do not equate REQ time with RUN or calibrate hardware.
  for (unsigned hold:{2000u,3000u,4000u,4500u,5000u}) {
    unsigned minimum=3000,maximum=0;
    for (unsigned phase=0;phase<20;++phase) {
      Rig r; r.ready(); const unsigned received=400+phase;
      r.advance(received); auto on=r.start(hold,phase%3+1); r.advance(900);
      assert(r.send(on).duplicate);
      r.advance(received+hold+20);
      assert(!r.esp.requests() && !r.wire_req && !r.pump());
      const unsigned expected_off=((received+hold+19)/20)*20;
      assert(r.request_on==420 && r.request_off==expected_off && r.request_rises==1);
      assert(r.preopen_at==440 && r.trigger_at==1440 && r.first_run==1441);
      const unsigned available=expected_off-r.first_run;
      const unsigned expected_run=available<3000?available:3000;
      assert(r.pump_ms==expected_run && r.run_end==r.first_run+expected_run);
      if (hold>=4500) assert(r.pump_ms==3000); // Reaches native RUN cap without stuck-wire fault.
      if (r.pump_ms<minimum) minimum=r.pump_ms;
      if (r.pump_ms>maximum) maximum=r.pump_ms;
      r.no_resume(received+6999);
      assert(r.trigger_count==1 && bridge_phase()==S_IDLE);
      auto replay=r.send(on); // Cache may be evicted; replay must never reactivate.
      assert(!replay.requested && !r.esp.requests());
      assert(!strcmp(r.send(r.make("on",1,5000)).reason,"bridge_recycle_wait"));
      r.advance(received+7000);
      assert(!r.wire_req && r.now-r.request_off>=20 && r.trigger_count==1);
      assert(r.send(r.make("on",1,5000)).requested); // Only a fresh command may start next cycle.
      ++cases;
    }
    printf("PHASE_SWEEP: receipt_phase_ms=0..19 request_hold_ms=%u virtual_run_min_ms=%u "
      "virtual_run_max_ms=%u native_run_cap_ms=3000 recycle_ms=7000; physical_tests=0\n",hold,minimum,maximum);
  }
  {
    Rig r; r.ready(); auto expired=r.make("on",1,5000,1); r.advance(402);
    assert(!strcmp(r.send(expired).reason,"command_expired_or_invalid_time"));
    r.advance(3000); assert(!r.esp.requests() && !r.pump_ms); ++cases;
  }
  for (const char *action:{"off","stop"}) {
    Rig r; r.running(); auto safe=r.make(action,!strcmp(action,"off")?1:0,0,1);
    r.advance(1602); // Expired safety commands still remove the request.
    assert(!strcmp(r.send(safe).status,"requested"));
    r.advance(1620); assert(!r.pump() && !r.esp.requests());
    r.no_resume(8000); ++cases;
  }
  for (const char *action:{"off","stop"}) {
    Rig r; r.ready(); r.start(5000); r.advance(800); // Cancel in PREOPEN: never pulse pump.
    assert(!strcmp(r.send(r.make(action,!strcmp(action,"off")?1:0,0)).status,"requested"));
    r.advance(820); assert(!r.pump_ms && !r.esp.requests()); r.no_resume(8000); ++cases;
  }
  for (bool disconnect:{false,true}) {
    Rig r; r.running(); r.renew=false;
    if (disconnect) r.network=false;
    r.advance(disconnect?1620:2500);
    assert(!r.esp.requests() && !r.pump());
    r.no_resume(8000); ++cases;
  }
  for (bool level_fault:{false,true}) {
    Rig r; r.running();
    if (level_fault) r.level=false; else r.leak=false;
    r.advance(1601); assert(!r.pump() && bridge_phase()==S_FAULT);
    r.advance(1620); assert(!r.esp.requests());
    r.level=r.leak=true; r.no_resume(8000);
    assert(bridge_phase()==S_DISARMED); ++cases;
  }
  {
    Rig r; r.ready(); r.respond_window=false; r.start(5000); r.advance(1541);
    assert(!r.pump_ms && (r.outputs&(1u<<18) || bridge_phase()==S_DISARMED));
    r.advance(1560); assert(!r.esp.requests()); r.no_resume(8000); ++cases;
  }
  for (unsigned delay:{1u,50u,99u,100u,101u}) {
    Rig r; r.ready(); r.window_delay=delay; r.start(5000); r.advance(7000);
    if (delay<=100) {
      assert(r.first_run==1440+delay && r.pump_ms==3000 && bridge_phase()==S_IDLE);
    } else {
      assert(!r.pump_ms && !r.armed && bridge_phase()==S_DISARMED);
    }
    assert(r.trigger_count==1 && r.request_rises==1);
    r.no_resume(8000); ++cases;
  }
  {
    Rig r; r.running(); r.cut_window=true; r.advance(1601);
    assert(!r.pump() && bridge_phase()==S_FAULT);
    r.advance(1620); r.no_resume(8000); ++cases;
  }
  {
    Rig r; r.running(); r.freeze_hb=true; r.advance(2600);
    assert(!r.pump() && !r.armed); r.advance(2620); r.no_resume(8000); ++cases;
  }
  { // Explicit stuck-HIGH wire fault reaches the native RUN cap non-vacuously.
    Rig r; r.running(); r.stuck_req=true; r.advance(5500);
    assert(!r.esp.requests() && !r.pump() && r.pump_ms==3000 && r.longest_run==3000);
    const auto before=r.pump_ms; r.advance(8000);
    assert(r.pump_ms==before && bridge_phase()==S_RELEASE_WAIT); ++cases;
  }
  printf("PASS: %u coupled native ESP/Pico source scenarios; virtual milliseconds, ideal external pins; physical_tests=0\n",cases);
}
"""


R15_ARCHIVE_SHA256 = "51a3a941ab124e46892d4f8f3656567000f2fa67ba0ce6a2ee33a01dd0c8b370"
R15_SOURCE_HASHES = {
    "host_bridge.c": "3ef5a809b0f142926459decc5c04f90b325b04157daee9d45bf2e103451820dd",
    "main.c": "b0235766e31fa08c49c3ac6b15bd2d1edcfa451672e1c232c257ba11dfabee77",
    "sequencer.c": "7ec817c7822d9bc337d5192a3c98f5b19f92e98f326188660092f9344ffc6b2c",
    "sequencer.h": "7773d5f693c52f1b4b36b72c2f696fbd4fe6e38949372b31ec156efa94e90141",
}


def sha256_file(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_r15_archive(archive, directory, root, compiler, env):
    """Compile only the frozen source allowlist, never bundled executables/scripts."""
    c_compiler = shutil.which("gcc") or shutil.which("clang")
    if not c_compiler:
        raise SystemExit("--r15-archive requires an existing gcc or clang; nothing was installed.")
    if not archive.is_file():
        raise SystemExit("The reviewed R15 archive is unavailable: " + str(archive))
    if sha256_file(archive) != R15_ARCHIVE_SHA256:
        raise SystemExit("R15 archive does not match the reviewed frozen release SHA256.")
    bridge_header = root / "firmware/cage_node/r15_bridge.h"
    bridge_sha256 = sha256_file(bridge_header)
    with zipfile.ZipFile(archive) as bundle:
        for name, expected in R15_SOURCE_HASHES.items():
            member = "HabitatOS_R15/circuit/pico/src/" + name
            matches = [info for info in bundle.infolist() if info.filename == member]
            if len(matches) != 1 or matches[0].file_size > 100_000:
                raise SystemExit("Missing, duplicate or oversized R15 source: " + name)
            content = bundle.read(matches[0])
            if hashlib.sha256(content).hexdigest() != expected:
                raise SystemExit("R15 source hash mismatch: " + name)
            if name != "main.c":  # SDK main is evidence only; no hardware entrypoint is built.
                (directory / name).write_bytes(content)
    source = directory / "pico_contract.cpp"
    source.write_text(PICO_CHECKS, encoding="utf-8")
    binary = directory / ("pico_contract.exe" if os.name == "nt" else "pico_contract")
    objects = []
    started = time.perf_counter()
    for name in ("sequencer", "host_bridge"):
        obj = directory / (name + ".o")
        subprocess.run([c_compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
                        "-c", str(directory / (name + ".c")), "-o", str(obj)],
                       check=True, timeout=60, env=env)
        objects.append(str(obj))
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pedantic",
                    "-I", str(root / "firmware/cage_node"), str(source), *objects,
                    "-o", str(binary)], check=True, timeout=60, env=env)
    compiled = time.perf_counter()
    subprocess.run([str(binary)], check=True, timeout=15, env=env)
    finished = time.perf_counter()
    if sha256_file(archive) != R15_ARCHIVE_SHA256:
        raise SystemExit("R15 archive changed during the check.")
    if sha256_file(bridge_header) != bridge_sha256:
        raise SystemExit("The ESP request bridge source changed during the check.")
    print(json.dumps({
        "check": "native_esp_pico_source_contract", "passed": True,
        "archive_sha256": R15_ARCHIVE_SHA256, "archive_unchanged": True,
        "source_sha256": R15_SOURCE_HASHES,
        "r15_bridge_sha256": bridge_sha256, "bridge_source_unchanged": True,
        "test_sha256": sha256_file(Path(__file__)),
        "scenario_count": 123,
        "scenarios": ["factory_bench_output_lock", "esp_request_output_lock",
                      "hold_1000_duplicate_recycle", "hold_2000_duplicate_recycle",
                      "hold_3000_duplicate_recycle", "expired_on",
                      "receipt_phase_0_to_19_by_hold_2000_3000_4000_4500_5000",
                      "expired_off_during_run", "expired_stop_during_run",
                      "off_during_preopen", "stop_during_preopen",
                      "gateway_lease_loss", "network_disconnect", "leak_fault",
                      "level_fault", "window_missing", "window_drops",
                      "window_response_delay_1_50_99_100_101_ms",
                      "esp_hb_wire_frozen", "request_wire_stuck_high_run_cap"],
        "compile_wall_seconds": round(compiled-started, 6),
        "execute_wall_seconds": round(finished-compiled, 6),
        "clock": "virtual_1ms_pico_20ms_esp", "window_fixture_ms": 5000,
        "request_hold_cap_ms": 5000, "native_run_cap_ms": 3000,
        "receipt_phase_ms": list(range(20)), "phase_sweep_hold_ms": [2000, 3000, 4000, 4500, 5000],
        "window_response_delays_ms": [1, 50, 99, 100, 101],
        "recycle_ms": 7000, "ttl_admission_ms": 5000, "gateway_lease_ms": 1000,
        "physical_tests": 0, "field_validated": False,
        "scope": "Actual native sequencer and request bridge; ideal ARM/WINDOW/health pins. "
                 "Host commissioning override only; Gateway/MQTT, main.c/SDK, physical GPIO timing, analog "
                 "protection, hydraulics and actual RUN feedback are not executed or proven.",
    }, sort_keys=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--r15-archive", type=Path,
                        help="Optionally couple the reviewed R15 ZIP's native Pico C source; no extraction persists.")
    args = parser.parse_args()
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler:
        raise SystemExit("An existing g++ or clang++ is required; nothing was installed.")
    root = Path(__file__).resolve().parents[2]
    sketch = (root / "firmware/cage_node/cage_node.ino").read_text(encoding="utf-8")
    start = sketch.index("void setProbeDiagnostic(")
    functions = sketch[start:sketch.index("\nString reading(", start)]
    pins_start = sketch.index("constexpr uint8_t shtSdaPin")
    sensor_pins = sketch[pins_start:sketch.index("\nOneWire hotBus", pins_start)]
    config_start = sketch.index("// Sensor GPIO configuration:")
    sensor_config = sketch[config_start:sketch.index("// End sensor GPIO configuration.", config_start)]
    guard_start = sketch.index("#ifndef HABITAT_R15_CENTRAL")
    role_guard = sketch[guard_start:config_start]
    log_start = sketch.index("void logSensorDiagnostics(")
    sensor_log = sketch[log_start:sketch.index("\nString uuid(", log_start)]
    task_start = sketch.index("void r15SafetyTask(")
    task = sketch[task_start:sketch.index("\nbool r15PublishAck(", task_start)]
    hello_start = sketch.index("  char payload[1024];", sketch.index("void r15Service("))
    hello = sketch[hello_start:sketch.index("\n  if (size>0", hello_start)]
    with tempfile.TemporaryDirectory(prefix="habitat-cage-node-check-") as directory:
        source = Path(directory) / "check.cpp"
        binary = Path(directory) / ("check.exe" if os.name == "nt" else "check")
        source.write_text(MOCKS + role_guard + sensor_config + BRIDGE_CHECKS + GPIO_MOCKS + task + GPIO_CHECKS +
                          sensor_pins + SENSOR_DIAGNOSTIC_MOCKS + sensor_log + SENSOR_DIAGNOSTIC_CHECKS +
                          HELLO_MOCKS + hello + HELLO_CHECKS + functions + CHECKS,
                          encoding="utf-8")
        env = dict(os.environ)
        env["PATH"] = str(Path(compiler).parent) + os.pathsep + env.get("PATH", "")
        keys = ("HABITAT_SHT_SDA_PIN", "HABITAT_SHT_SCL_PIN", "HABITAT_T2_PIN", "HABITAT_T3_PIN")
        new_pins = [f"-D{key}={pin}" for key, pin in zip(keys, (25, 26, 32, 33))]
        for label, flags, expected in (("legacy", [], (21, 22, 18, 19)),
                                       ("38pin", new_pins, (25, 26, 32, 33))):
            expectation = Path(directory) / "expected.h"
            expectation.write_text(sensor_config + sensor_pins + "\n" +
                "\n".join(f"static_assert({key} == {pin}, \"pin mapping\");"
                          for key, pin in zip(("shtSdaPin", "shtSclPin", "hotPin", "coolPin"), expected)))
            # Compile actual GPIO configuration separately to verify defaults/overrides.
            subprocess.run([compiler, "-std=c++17", "-include", "cstdint", "-x", "c++", "-fsyntax-only",
                            *flags, str(expectation)], check=True)
            subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pedantic",
                            *flags, "-I", str(root / "firmware/cage_node"), str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True, env=env)
            print(f"PASS: {label} GPIO configuration and sensor regressions", flush=True)
        invalid = Path(directory) / "invalid.cpp"
        invalid.write_text(role_guard + sensor_config)
        for flags, reason in (([new_pins[0]], "Configure all four"),
                              ([*new_pins[:3], "-DHABITAT_T3_PIN=32"], "must be distinct"),
                              ([*new_pins[:3], "-DHABITAT_T3_PIN=34"], "available classic ESP32"),
                              ([*new_pins, "-DHABITAT_R15_CENTRAL=1"], "both R15 options"),
                              ([*new_pins, "-DHABITAT_R15_REQUEST_OUTPUTS=1"], "both R15 options")):
            result = subprocess.run([compiler, "-std=c++17", "-fsyntax-only", *flags, str(invalid)],
                                    capture_output=True, text=True)
            assert result.returncode != 0 and reason in result.stderr, result.stderr
        print("PASS: partial, duplicate, input-only GPIO and both R15 conflicts rejected")
        if args.r15_archive:
            check_r15_archive(args.r15_archive, Path(directory), root, compiler, env)
    if args.r15_archive:
        assert not Path(directory).exists()
        print("PASS: temporary compiled sources and binaries removed; no device or archive was changed.")


if __name__ == "__main__":
    main()
