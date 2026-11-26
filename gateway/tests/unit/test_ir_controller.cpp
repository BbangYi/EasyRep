#include "../../firmware/cage_node/ir_controller.h"
#include <cstdio>
#include <cstring>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
constexpr const char *SESSION="11111111-1111-4111-8111-111111111111";
constexpr const char *FRESH="22222222-2222-4222-8222-222222222222";
constexpr uint64_t UTC=1800000000000ULL;
void check(bool v,const char *why){if(!v)throw std::runtime_error(why);}
bool eq(const char*a,const char*b){return std::string(a)==b;}
struct Fixture{
  ir::Controller c;uint32_t now=10000,seq=0,id=0;
  explicit Fixture(bool enabled=true):c(enabled){c.connect(SESSION);c.tick(now,true);}
  r15::Command command(r15::Action action=r15::Action::On,uint32_t hold=5000,unsigned zone=1){
    r15::Command x;std::strcpy(x.session,c.session());std::snprintf(x.id,sizeof(x.id),"00000000-0000-4000-8000-%012u",++id);
    x.sequence=++seq;x.action=action;x.zone=zone;x.hold_ms=hold;x.issued_ms=UTC+now;x.expires_ms=x.issued_ms+5000;return x;
  }
  const char *send(const r15::Command &x){return c.receive(x,UTC+now,now);}
  r15::Command start(unsigned hold=5000){auto x=command(r15::Action::On,hold);check(eq(send(x),"ir_requested_on")&&c.on(),"valid on rejected");return x;}
  void tick(uint32_t at,bool network=true){now=at;c.tick(now,network);}
};
int main(){
  using Test=std::pair<std::string,std::function<void()>>;std::vector<Test> tests;
  auto add=[&](std::string n,std::function<void()> f){tests.emplace_back(n,f);};
  add("defaults_GPIO4_20ms_5000ms_and_OFF",[]{ir::Controller c;check(ir::PIN==4&&ir::TICK_MS==20&&ir::MAX_LEASE_MS==5000,"contract changed");check(!c.on()&&eq(c.reason(),"boot_off"),"boot not OFF");});
  add("outputs_locked_by_default",[]{Fixture f(false);check(eq(f.send(f.command()),"outputs_locked")&&!f.c.on(),"lock bypass");});
  add("valid_binary_ON_and_exact_expiry",[]{Fixture f;f.start();f.tick(14999);check(f.c.on(),"early expiry");f.tick(15000);check(!f.c.on()&&eq(f.c.reason(),"lease_expired"),"expiry late");});
  add("one_millisecond_lease_supported",[]{Fixture f;f.start(1);f.tick(10001);check(!f.c.on(),"short lease ignored");});
  add("hold_zero_and_over5000_rejected",[]{Fixture f;for(unsigned d:{0u,5001u,UINT32_MAX})check(eq(f.send(f.command(r15::Action::On,d)),"invalid_lease")&&!f.c.on(),"unbounded hold");});
  add("fresh_ON_every_second_renews_without_pump_cooldown",[]{Fixture f;f.start();for(unsigned i=1;i<=20;++i){f.tick(10000+i*1000);f.start();check(f.c.on(),"fresh renewable lease interrupted");}f.tick(34999);check(f.c.on(),"last renewal too short");f.tick(35000);check(!f.c.on(),"last renewal never expired");});
  add("duplicate_ON_does_not_renew",[]{Fixture f;auto x=f.start();f.now=14000;check(eq(f.send(x),"duplicate_id"),"duplicate accepted");f.tick(15000);check(!f.c.on(),"duplicate extended lease");});
  add("duplicate_id_with_changed_payload_does_not_renew",[]{Fixture f;auto x=f.start();f.now=14000;x.sequence++;x.issued_ms=UTC+f.now;x.expires_ms=x.issued_ms+5000;check(eq(f.send(x),"duplicate_id"),"conflicting duplicate accepted");f.tick(15000);check(!f.c.on(),"conflicting duplicate extended");});
  add("stale_sequence_new_id_does_not_renew",[]{Fixture f;f.start();f.now=14000;auto x=f.command();x.sequence=1;check(eq(f.send(x),"stale_sequence"),"old seq accepted");f.tick(15000);check(!f.c.on(),"old seq extended");});
  add("evicted_old_packet_still_rejected_by_sequence",[]{Fixture f;auto old=f.start();for(int i=0;i<20;++i){f.now+=1;f.start();}check(eq(f.send(old),"stale_sequence"),"evicted replay accepted");});
  add("wrong_zone_and_foreign_session_cannot_activate",[]{Fixture f;for(unsigned z:{0u,2u,3u})check(eq(f.send(f.command(r15::Action::On,1000,z)),"wrong_zone"),"wrong zone");auto x=f.command();std::strcpy(x.session,FRESH);check(eq(f.send(x),"session_mismatch")&&!f.c.on(),"wrong session");});
  add("heartbeat_is_rejected_and_cannot_extend_ON",[]{Fixture f;f.start();f.now=14000;check(eq(f.send(f.command(r15::Action::Heartbeat,0,0)),"unsupported_action"),"heartbeat accepted");f.tick(15000);check(!f.c.on(),"heartbeat extended lease");});
  add("network_false_trips_and_new_ON_is_blocked",[]{Fixture f;f.start();f.tick(10020,false);check(!f.c.on(),"disconnect stayed ON");check(eq(f.send(f.command()),"network_offline")&&!f.c.on(),"offline renewal");});
  add("network_recovery_alone_does_not_resume",[]{Fixture f;f.start();f.tick(10020,false);f.tick(10040,true);check(!f.c.on(),"network recovery auto-resumed");});
  add("disconnect_reconnect_changes_nonce_and_stays_OFF",[]{Fixture f;auto old=f.start();f.c.disconnect();f.c.connect(FRESH);f.tick(10020);check(!f.c.on()&&eq(f.send(old),"session_mismatch"),"reconnect replay");f.start();});
  add("new_boot_cannot_replay_previous_ON",[]{Fixture f;auto old=f.start();ir::Controller reboot(true);reboot.connect(FRESH);reboot.tick(0,true);check(!reboot.on()&&eq(reboot.receive(old,UTC,0),"session_mismatch"),"boot replay");});
  add("OFF_ignores_expired_time_and_reordered_sequence",[]{Fixture f;f.start();auto x=f.command(r15::Action::Off,0);x.sequence=0;x.issued_ms=0;x.expires_ms=1;check(eq(f.c.receive(x,0,f.now),"off_requested")&&!f.c.on(),"safety off gated");});
  add("OFF_allows_later_explicit_ON",[]{Fixture f;f.start();f.send(f.command(r15::Action::Off,0));check(!f.c.on(),"off ignored");f.start();});
  add("STOP_latches_until_new_connection",[]{Fixture f;f.start();f.send(f.command(r15::Action::Stop,0,0));check(!f.c.on()&&eq(f.send(f.command()),"stop_latched"),"stop latch missing");f.c.connect(FRESH);f.tick(10020);f.start();});
  add("foreign_OFF_does_not_control_this_session",[]{Fixture f;f.start();auto x=f.command(r15::Action::Off,0);std::strcpy(x.session,FRESH);check(eq(f.send(x),"session_mismatch")&&f.c.on(),"foreign off accepted");});
  add("invalid_UTC_freshness_and_TTL_boundaries",[]{for(unsigned k=0;k<5;++k){Fixture f;auto x=f.command();uint64_t now=UTC+f.now;if(k==0)now=0;if(k==1)x.issued_ms=now+ir::MAX_CLOCK_SKEW_MS+1;if(k==2)x.expires_ms=now;if(k==3)x.expires_ms=x.issued_ms;if(k==4)x.expires_ms=x.issued_ms+5001;check(eq(f.c.receive(x,now,f.now),"invalid_time")&&!f.c.on(),"invalid TTL/time allowed");}});
  add("issuer_ahead_up_to_one_second_is_accepted",[]{
    check(ir::MAX_CLOCK_SKEW_MS==1000,"clock admission bound changed");
    for(unsigned ahead:{1u,999u,1000u}){
      Fixture f;auto x=f.command();x.issued_ms+=ahead;x.expires_ms+=ahead;
      check(eq(f.send(x),"ir_requested_on")&&f.c.on(),"bounded issuer skew rejected");
    }
  });
  add("issuer_ahead_over_one_second_is_rejected",[]{
    for(uint64_t ahead:{1001ULL,10000ULL,9007199254740991ULL-UTC-15000ULL}){
      Fixture f;auto x=f.command();x.issued_ms+=ahead;x.expires_ms+=ahead;
      check(eq(f.send(x),"invalid_time")&&!f.c.on(),"excess issuer skew accepted");
    }
  });
  add("future_issued_command_cannot_extend_monotonic_lease",[]{
    for(unsigned hold:{1u,1000u,5000u}){
      Fixture f;auto x=f.command(r15::Action::On,hold);
      x.issued_ms+=1000;x.expires_ms=x.issued_ms+hold;
      check(eq(f.send(x),"ir_requested_on"),"future-issued valid lease rejected");
      f.tick(10000+hold-1);check(f.c.on(),"future-issued lease expired early");
      f.tick(10000+hold);check(!f.c.on(),"clock tolerance extended physical lease");
    }
  });
  add("clock_tolerance_does_not_revive_expired_command",[]{
    for(unsigned expired_by:{0u,1u,1000u}){
      Fixture f;auto x=f.command();x.expires_ms=UTC+f.now-expired_by;x.issued_ms=x.expires_ms-5000;
      check(eq(f.send(x),"invalid_time")&&!f.c.on(),"expired command revived by clock tolerance");
    }
  });
  add("rejected_future_renewal_does_not_extend_existing_lease",[]{
    Fixture f;f.start();f.tick(14000);auto x=f.command();
    x.issued_ms+=1001;x.expires_ms+=1001;
    check(eq(f.send(x),"invalid_time")&&f.c.on(),"future renewal admission changed");
    f.tick(15000);check(!f.c.on(),"rejected renewal extended existing lease");
  });
  add("lease_capped_by_remaining_TTL",[]{Fixture f;auto x=f.command();x.expires_ms=x.issued_ms+1500;check(eq(f.send(x),"ir_requested_on"),"short ttl rejected");f.tick(11499);check(f.c.on(),"ttl cutoff early");f.tick(11500);check(!f.c.on(),"remaining TTL ignored");});
  add("monotonic_lease_survives_wall_clock_jump",[]{Fixture f;f.start();auto x=f.command();check(eq(f.c.receive(x,0,f.now),"invalid_time"),"bad wallclock allowed new ON");f.tick(15000);check(!f.c.on(),"wallclock affected existing deadline");});
  add("lease_crosses_millis_wrap",[]{Fixture f;f.tick(0xfffffff0u);f.start();f.tick(uint32_t(0xfffffff0u+4999));check(f.c.on(),"wrap early");f.tick(uint32_t(0xfffffff0u+5000));check(!f.c.on(),"wrap expired late");});
  add("sequence_wrap_requires_new_session",[]{Fixture f;auto x=f.command();x.sequence=UINT32_MAX;check(eq(f.send(x),"ir_requested_on"),"maxseq valid");auto next=f.command();next.sequence=1;check(eq(f.send(next),"stale_sequence"),"seq wrap bypass");});
  add("invalid_connect_nonce_stays_OFF",[]{Fixture f;f.start();f.c.connect("bad");check(!f.c.on(),"bad session connect not OFF");});
  add("IR_prefix_explicit_and_R11_R15_are_rejected",[]{std::string x=std::string("IR/1 ")+SESSION+" 00000000-0000-4000-8000-000000000001 1 1 on 5000 1800000000000 1800000005000";r15::Command c;check(r15::parse(reinterpret_cast<const uint8_t*>(x.data()),x.size(),c,"IR/1"),"IR parse failed");check(!r15::parse(reinterpret_cast<const uint8_t*>(x.data()),x.size(),c),"R15 accepted IR");for(const char*p:{"R11/1","R15/1"}){auto other=std::string(p)+x.substr(4);check(!r15::parse(reinterpret_cast<const uint8_t*>(other.data()),other.size(),c,"IR/1"),"cross protocol accepted");}});
  add("existing_R15_default_parser_and_fields_are_preserved",[]{
    std::string x=std::string("R15/1 ")+SESSION+" 00000000-0000-4000-8000-000000000001 42 3 on 3000 1800000000000 1800000005000";
    r15::Command current,explicitVersion;
    check(r15::parse(reinterpret_cast<const uint8_t*>(x.data()),x.size(),current),"legacy default R15 rejected");
    check(r15::parse(reinterpret_cast<const uint8_t*>(x.data()),x.size(),explicitVersion,"R15/1"),"explicit R15 rejected");
    check(r15::same(current,explicitVersion),"default parser changed fields");
    check(current.sequence==42&&current.zone==3&&current.action==r15::Action::On&&current.hold_ms==3000,"legacy field values changed");
    check(!r15::parse(reinterpret_cast<const uint8_t*>(x.data()),x.size(),explicitVersion,"IR/1"),"IR accepted R15 frame");
  });
  add("parser_rejects_oversized_binary_trailing_and_bad_fields",[]{std::string x=std::string("IR/1 ")+SESSION+" 00000000-0000-4000-8000-000000000001 1 1 on 5000 1800000000000 1800000005000";std::vector<std::string> bad={"",std::string(257,'A'),x+" ",x+"\n",x+" extra"," "+x};auto nul=x;nul[8]='\0';bad.push_back(nul);auto over=x;over.replace(over.find(" on 5000"),8," on 5001");bad.push_back(over);for(const auto&s:bad){r15::Command c;check(!r15::parse(reinterpret_cast<const uint8_t*>(s.data()),s.size(),c,"IR/1"),"bad frame accepted");}});
  unsigned failed=0;std::cout<<"{\"suite\":\"IR-production-controller-parser\",\"hardware_tested\":false,\"cases\":[\n";
  for(size_t i=0;i<tests.size();++i){std::string error;try{tests[i].second();}catch(const std::exception&e){++failed;error=e.what();}std::cout<<"{\"name\":\""<<tests[i].first<<"\",\"passed\":"<<(error.empty()?"true":"false");if(!error.empty())std::cout<<",\"error\":\""<<error<<"\"";std::cout<<"}"<<(i+1<tests.size()?",\n":"\n");}
  std::cout<<"],\"total\":"<<tests.size()<<",\"failed\":"<<failed<<"}\n";return failed?1:0;
}
