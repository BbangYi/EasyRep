#pragma once
#include "r15_bridge.h"

namespace ir {
constexpr unsigned PIN=4;
constexpr uint32_t TICK_MS=20, MAX_LEASE_MS=5000;
// Pi and ESP synchronize UTC independently. Admit at most 1s of issuer-ahead
// skew; an already-expired command is never revived and the monotonic lease
// below remains bounded by hold_ms (at most 5s) from receipt.
constexpr uint32_t MAX_CLOCK_SKEW_MS=1000;

// Binary IR output only. No sensor, water, camera UART or pump policy ownership.
class Controller {
 public:
  explicit Controller(bool enabled=false):enabled_(enabled) {}
  void connect(const char *nonce) {
    disconnect();
    if (!nonce || !r15::uuid(nonce)) return;
    memcpy(session_,nonce,37);connected_=true;stopped_=false;
    high_sequence_=0;used_=0;reason_="connected_off";
  }
  void disconnect() { stop("connection_lost");connected_=network_=false; }
  void tick(uint32_t now,bool network) {
    network_=network;
    if (!network || !connected_) { if (on_) stop("connection_lost");return; }
    if (on_ && r15::passed(now,lease_at_,lease_ms_)) stop("lease_expired");
  }
  const char *receive(const r15::Command &c,uint64_t utc,uint32_t now) {
    if (!connected_ || strcmp(c.session,session_)) return "session_mismatch";
    if (c.action==r15::Action::Heartbeat) return "unsupported_action";
    if ((c.action==r15::Action::On || c.action==r15::Action::Off) ? c.zone!=1 : c.zone!=0) return "wrong_zone";
    const bool off=c.action==r15::Action::Off || c.action==r15::Action::Stop;
    // A valid current-session safety OFF cannot be defeated by bad time or ordering.
    if (off) { stop(c.action==r15::Action::Stop?"stop_requested":"off_requested");if(c.action==r15::Action::Stop)stopped_=true; }
    for(size_t i=0;i<used_;++i)if(!strcmp(ids_[i],c.id))return "duplicate_id";
    if(c.sequence<=high_sequence_ && !off)return "stale_sequence";
    if(c.sequence>high_sequence_)high_sequence_=c.sequence;
    if(used_==16){memmove(ids_,ids_+1,15*37);--used_;}
    memcpy(ids_[used_++],c.id,37);
    if(off)return reason_;
    if(c.action!=r15::Action::On || !c.hold_ms || c.hold_ms>MAX_LEASE_MS)return "invalid_lease";
    const bool issued_too_far_ahead=c.issued_ms>utc && c.issued_ms-utc>MAX_CLOCK_SKEW_MS;
    if(utc<1700000000000ULL || issued_too_far_ahead || c.expires_ms<=utc ||
       c.expires_ms<=c.issued_ms || c.expires_ms-c.issued_ms>r15::MAX_TTL_MS)return "invalid_time";
    if(!enabled_)return "outputs_locked";
    if(stopped_)return "stop_latched";
    if(!network_)return "network_offline";
    const uint64_t remaining=c.expires_ms-utc;
    lease_ms_=uint32_t(remaining<c.hold_ms?remaining:c.hold_ms);
    lease_at_=now;on_=true;reason_="ir_requested_on";return reason_;
  }
  void stop(const char *why){on_=false;reason_=why;}
  bool on()const{return on_;}
  const char *session()const{return session_;}
  const char *reason()const{return reason_;}
 private:
  bool enabled_,on_=false,connected_=false,network_=false,stopped_=false;
  char session_[37]={},ids_[16][37]={};size_t used_=0;
  uint32_t high_sequence_=0,lease_at_=0,lease_ms_=0;
  const char *reason_="boot_off";
};
} // namespace ir
