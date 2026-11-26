#pragma once
// R15 J112 request bridge. No GPIO, network, allocation or physical-ACK assumptions.
#include <stdint.h>
#include <stddef.h>
#include <string.h>

namespace r15 {
constexpr size_t MAX_FRAME = 256;
// REQ includes qualification/PREOPEN/WINDOW wait; it is not pump RUN time.
// The original Pico independently caps RUN at 3000ms. TTL is admission freshness.
constexpr uint32_t MAX_HOLD_MS = 5000, MAX_TTL_MS = 5000, LINK_LEASE_MS = 1000;
// More than the documented 1s preopen + 5.2054s maximum modelled window.
// This is a protocol guard, not measured hydraulic calibration.
constexpr uint32_t RECYCLE_MS = 7000;
enum class Action { On, Off, Stop, Heartbeat };
struct Command {
  char session[37] = {}, id[37] = {};
  uint32_t sequence = 0, zone = 0, hold_ms = 0;
  uint64_t issued_ms = 0, expires_ms = 0;
  Action action = Action::Stop;
};
inline bool uuid(const char *s) {
  if (strlen(s) != 36) return false;
  for (size_t i=0; i<36; ++i) {
    if (i==8 || i==13 || i==18 || i==23) { if (s[i]!='-') return false; }
    else if (!((s[i]>='0' && s[i]<='9') || (s[i]>='a' && s[i]<='f'))) return false;
  }
  return true;
}
inline bool number(const char *s, uint64_t maximum, uint64_t &out) {
  if (!*s || (s[0]=='0' && s[1])) return false;
  out=0;
  for (; *s; ++s) {
    if (*s<'0' || *s>'9' || uint64_t(*s-'0')>maximum || out>(maximum-uint64_t(*s-'0'))/10) return false;
    out=out*10+uint64_t(*s-'0');
  }
  return out<=maximum;
}
// Exactly nine space-separated ASCII fields. No JSON parser or implicit coercion.
inline bool parse(const uint8_t *data, size_t size, Command &out, const char *version="R15/1") {
  if (!size || size>MAX_FRAME) return false;
  char frame[MAX_FRAME+1]; const char *fields[9]; size_t count=1;
  fields[0]=frame;
  for (size_t i=0; i<size; ++i) {
    if (data[i]<32 || data[i]>126) return false;
    frame[i]=char(data[i]);
    if (frame[i]==' ') {
      if (!i || data[i-1]==' ' || count==9 || i+1==size) return false;
      frame[i]=0; fields[count++]=frame+i+1;
    }
  }
  frame[size]=0;
  if (count!=9 || strcmp(fields[0],version) || !uuid(fields[1]) || !uuid(fields[2])) return false;
  Command c; uint64_t value;
  memcpy(c.session,fields[1],37); memcpy(c.id,fields[2],37);
  if (!number(fields[3],UINT32_MAX,value) || !value) return false;
  c.sequence=uint32_t(value);
  if (!number(fields[4],3,value)) return false;
  c.zone=uint32_t(value);
  if (!strcmp(fields[5],"on")) c.action=Action::On;
  else if (!strcmp(fields[5],"off")) c.action=Action::Off;
  else if (!strcmp(fields[5],"stop")) c.action=Action::Stop;
  else if (!strcmp(fields[5],"heartbeat")) c.action=Action::Heartbeat;
  else return false;
  if (!number(fields[6],MAX_HOLD_MS,value)) return false;
  c.hold_ms=uint32_t(value);
  if (!number(fields[7],9007199254740991ULL,c.issued_ms) ||
      !number(fields[8],9007199254740991ULL,c.expires_ms)) return false;
  if (c.action==Action::On ? (!c.zone || !c.hold_ms) : c.hold_ms!=0) return false;
  if ((c.action==Action::Off && !c.zone) ||
      ((c.action==Action::Stop || c.action==Action::Heartbeat) && c.zone)) return false;
  out=c; return true;
}
inline bool same(const Command &a,const Command &b) {
  return !strcmp(a.session,b.session) && !strcmp(a.id,b.id) &&
    a.sequence==b.sequence && a.zone==b.zone && a.hold_ms==b.hold_ms &&
    a.issued_ms==b.issued_ms && a.expires_ms==b.expires_ms && a.action==b.action;
}
inline bool passed(uint32_t now,uint32_t then,uint32_t duration) { return uint32_t(now-then)>=duration; }
struct Result { const char *status; const char *reason; bool requested; bool duplicate; };
struct Completion { Command command; const char *reason; };
class Bridge {
 public:
  explicit Bridge(bool allow_requests=false): enabled(allow_requests) {}
  void connect(const char *nonce) {
    disconnect(); memcpy(session,nonce,37); high_sequence=0; used=0; connected=true;
    stopped=false; pending_completion=false; // Reconnect must not clear a cycle guard.
  }
  void disconnect() { release("connection_lost"); connected=false; linked=false; hb=false; }
  void tick(uint32_t now,bool network_ok,bool armed_pin,bool level_pin) {
    if (!network_ok || !connected || !linked || passed(now,link_at,link_for)) {
      release(network_ok?"gateway_lease_expired":"connection_lost"); linked=false; hb=false; return;
    }
    if (stopped) { release("stop_latched"); hb=false; return; }
    if (!armed_pin || !level_pin) release("r15_status_pin_low");
    if (mask && passed(now,request_at,request_hold)) release("request_hold_finished");
    if (passed(now,hb_at,100)) { hb=!hb; hb_at=now; }
  }
  Result receive(const Command &c,uint64_t utc_ms,uint32_t now,bool armed_pin,bool level_pin) {
    if (!connected || strcmp(c.session,session)) return {"rejected","session_mismatch",false,false};
    // Authenticated current-session OFF/STOP is always fail-OFF, even with a bad clock,
    // expired TTL or reordered sequence. Never renew the gateway lease here.
    const bool safety_off=c.action==Action::Off || c.action==Action::Stop;
    if (c.action==Action::Stop) { release("stop_requested"); hb=false; stopped=true; }
    else if (c.action==Action::Off && mask==uint8_t(1u<<(c.zone-1))) release("off_requested");
    for (size_t i=0;i<used;++i) if (!strcmp(cache[i].command.id,c.id)) {
      if (!same(cache[i].command,c)) return {"rejected","command_id_conflict",false,false};
      Result result=cache[i].result; result.duplicate=true; return result;
    }
    if (c.sequence<=high_sequence && !safety_off) return {"rejected","stale_sequence",false,false};
    if (c.sequence>high_sequence) high_sequence=c.sequence;
    const char *reason=nullptr;
    if (!safety_off) {
      if (utc_ms<1700000000000ULL) reason="clock_unavailable";
      else if (c.issued_ms>utc_ms || c.expires_ms<=utc_ms || c.expires_ms<=c.issued_ms ||
               c.expires_ms-c.issued_ms>MAX_TTL_MS) reason="command_expired_or_invalid_time";
    }
    if (!reason && c.action==Action::Heartbeat) {
      // Duplicate heartbeat packets cannot keep a dead gateway alive.
      if (utc_ms-c.issued_ms>=LINK_LEASE_MS) return remember(c,{"rejected","heartbeat_stale",false,false});
      linked=true; link_at=now;
      link_for=uint32_t(c.expires_ms-utc_ms<LINK_LEASE_MS?c.expires_ms-utc_ms:LINK_LEASE_MS);
      return remember(c,{"received",stopped?"stop_latched":"heartbeat_received",false,false});
    }
    if (!reason && c.action==Action::On) {
      if (!enabled) reason="outputs_locked";
      else if (stopped) reason="stop_latched";
      else if (!linked || passed(now,link_at,link_for)) reason="gateway_lease_expired";
      else if (!armed_pin || !level_pin) reason="r15_status_pin_low";
      else if (mask) reason="bridge_busy";
      else if (recycled && !passed(now,cycle_at,RECYCLE_MS)) reason="bridge_recycle_wait";
      else {
        mask=uint8_t(1u<<(c.zone-1)); request_at=cycle_at=now;
        request_hold=c.hold_ms; recycled=true; active_command=c;
      }
    }
    Result result={reason?"rejected":"requested",reason?reason:"physical_execution_unverified",
                   !reason && c.action==Action::On,false};
    return remember(c,result);
  }
  uint8_t requests() const { return mask; }
  bool heartbeat() const { return hb; }
  bool latched() const { return stopped; }
  bool lease(uint32_t now) const { return connected && linked && !passed(now,link_at,link_for); }
  const char *active() const { return mask?active_command.id:""; }
  const char *nonce() const { return session; }
  bool completion(Completion &out) const {
    if (!pending_completion) return false;
    out=completed; return true;
  }
  void acknowledged_completion(uint32_t sequence) {
    if (pending_completion && completed.command.sequence==sequence) pending_completion=false;
  }
 private:
  static constexpr size_t CACHE_SIZE=16;
  struct Entry { Command command; Result result; };
  Entry cache[CACHE_SIZE]{}; size_t used=0;
  bool enabled,connected=false,linked=false,stopped=false,recycled=false,hb=false;
  char session[37]{};
  Command active_command{}; Completion completed{}; bool pending_completion=false;
  uint32_t high_sequence=0,link_at=0,link_for=0,hb_at=0,request_at=0,request_hold=0,cycle_at=0;
  uint8_t mask=0;
  Result remember(const Command &command,Result result) {
    // Heartbeats also bind ID to payload. Sequence remains the replay barrier after eviction.
    if (used==CACHE_SIZE) {
      for(size_t i=1;i<CACHE_SIZE;++i) cache[i-1]=cache[i];
      --used;
    }
    cache[used++]={command,result}; return result;
  }
  void release(const char *reason) {
    if (!mask) return;
    mask=0; completed={active_command,reason}; pending_completion=true;
    for (size_t i=0;i<used;++i) if (!strcmp(cache[i].command.id,active_command.id))
      cache[i].result={"execution_unverified",reason,false,false};
  }
};
} // namespace r15
