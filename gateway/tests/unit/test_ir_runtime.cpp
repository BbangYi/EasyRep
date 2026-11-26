#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>
#include <sys/time.h>
#include <vector>
#define HABITAT_SHT_SDA_PIN 21
#define HABITAT_SHT_SCL_PIN 22
#define HABITAT_T2_PIN 18
#define HABITAT_T3_PIN 19
#ifndef HABITAT_IR_OUTPUTS
#define HABITAT_IR_OUTPUTS 1
#endif
#define TOPIC_BASE "habitat/v1/STORE-001/cages/CAGE-001/nodes/ESP32-001"
constexpr int LOW=0,HIGH=1,OUTPUT=1,WL_CONNECTED=3,pdPASS=1;
using String=std::string;using gpio_num_t=int;using TickType_t=uint32_t;using portMUX_TYPE=int;
#define portMUX_INITIALIZER_UNLOCKED 0
void check(bool v,const char *why){if(!v)throw std::runtime_error(why);}
struct Event{uint32_t at;std::string kind;unsigned pin;int value,depth;};
std::vector<Event> events;uint32_t fakeMs=0;int depth=0,taskResult=pdPASS,ticks=0;
bool requireLock=false;std::function<void()> betweenTicks,publishHook;
std::string nonce="11111111-1111-4111-8111-111111111111";
struct TaskExit{};
uint32_t millis(){return fakeMs;}
TickType_t xTaskGetTickCount(){return fakeMs;}
TickType_t pdMS_TO_TICKS(uint32_t v){return v;}
void portENTER_CRITICAL(portMUX_TYPE*){++depth;}
void portEXIT_CRITICAL(portMUX_TYPE*){check(depth==1,"critical lock imbalance");--depth;}
void gpio_set_level(gpio_num_t pin,int value){check(pin==4,"IR touched sensor/pump/camera pin");if(requireLock)check(depth==1,"GPIO outside state lock");events.push_back({fakeMs,"gpio",unsigned(pin),value,depth});}
void pinMode(unsigned pin,int value){check(pin==4 && value==OUTPUT,"IR pin ownership changed");events.push_back({fakeMs,"mode",pin,value,depth});}
void vTaskDelayUntil(TickType_t*wake,TickType_t period){check(period==20,"tick contract");*wake+=period;fakeMs=*wake;if(betweenTicks)betweenTicks();if(--ticks<=0)throw TaskExit{};}
int xTaskCreatePinnedToCore(void(*)(void*),const char*,unsigned,void*,unsigned,void*,int core){check(core==1,"core changed");return taskResult;}
struct{void println(const char*){check(depth==0,"Serial inside lock");}}Serial;
struct{int value=WL_CONNECTED;int status(){return value;}}WiFi;
struct Mqtt{
  bool online=true,subscribeOk=true;std::string subscribed;
  std::vector<std::pair<std::string,std::string>> published;
  bool connected(){check(depth==0,"MQTT inside lock");return online;}
  bool subscribe(const char*t,int qos){check(depth==0 && qos==1,"subscribe contract");subscribed=t;return subscribeOk;}
  bool publish(const char*t,const char*b,bool retained){check(depth==0&&!retained,"publish lock or retained output");published.emplace_back(t,b);if(publishHook)publishHook();return true;}
}mqtt;
String uuid(){return nonce;}
int fakeGettimeofday(struct timeval*v,void*){uint64_t t=1800000000000ULL+fakeMs;v->tv_sec=long(t/1000);v->tv_usec=long(t%1000*1000);return 0;}
#define gettimeofday fakeGettimeofday
#include "../../firmware/cage_node/ir_runtime.h"
#undef gettimeofday
uint32_t seq=0,id=0;
void reset(bool taskWorks=true){
  fakeMs=0;depth=0;events.clear();taskResult=taskWorks?pdPASS:0;betweenTicks={};publishHook={};mqtt=Mqtt{};WiFi.value=WL_CONNECTED;
  irControl=ir::Controller(HABITAT_IR_OUTPUTS==1);irReady=irNetwork=false;irTopic[0]=0;irNextStatus=0;seq=id=0;
  nonce="11111111-1111-4111-8111-111111111111";requireLock=false;irSetup();requireLock=true;
}
int lastGPIO(){for(auto i=events.rbegin();i!=events.rend();++i)if(i->kind=="gpio")return i->value;return -1;}
void runTicks(int n){ticks=n;try{irSafetyTask(nullptr);}catch(const TaskExit&){}check(depth==0,"task lock leaked");}
std::string frame(const char*action="on",unsigned hold=5000,unsigned zone=1){
  char s[256],commandId[37];std::snprintf(commandId,sizeof(commandId),"00000000-0000-4000-8000-%012u",++id);const uint64_t t=1800000000000ULL+fakeMs;
  std::snprintf(s,sizeof(s),"IR/1 %s %s %u %u %s %u %llu %llu",irControl.session(),commandId,++seq,zone,action,hold,(unsigned long long)t,(unsigned long long)(t+5000));return s;
}
void message(std::string data,const char*topic=nullptr){irMessage(const_cast<char*>(topic?topic:irTopic),reinterpret_cast<uint8_t*>(data.data()),unsigned(data.size()));}
void ready(){irConnected();fakeMs=10000;irService();}
void start(){message(frame());check(irControl.on()&&lastGPIO()==HIGH,"IR ON failed");}
int main(int argc,char**argv){
  std::ofstream trace;if(argc>1){trace.open(argv[1]);if(!trace)return 2;trace<<"test,time_ms,event,pin,value,critical_depth\n";}
  using Test=std::pair<std::string,std::function<void()>>;std::vector<Test> tests;
  auto add=[&](std::string n,std::function<void()>f){tests.emplace_back(n,f);};
  add("startup_LOW_before_OUTPUT_and_only_GPIO4",[]{reset();check(events.size()==2&&events[0].kind=="gpio"&&events[0].value==LOW&&events[1].kind=="mode","startup order");});
  add("task_creation_failure_rejects_all_control",[]{reset(false);irConnected();message("bad");check(!irReady&&!irNetwork&&!irControl.on()&&lastGPIO()==LOW,"failed task activation");});
#if HABITAT_IR_OUTPUTS == 0
  add("locked_build_valid_ON_never_HIGH",[]{reset();ready();message(frame());runTicks(5);for(const auto&e:events)if(e.kind=="gpio")check(e.value==LOW,"locked binary went HIGH");check(!irControl.on(),"locked state ON");});
  add("locked_build_status_explicitly_reports_lock",[]{reset();ready();check(!mqtt.published.empty(),"no hello");check(mqtt.published.back().second.find("\"outputs_locked\":true")!=std::string::npos,"lock status wrong");});
#else
  add("valid_ON_applies_GPIO_inside_same_lock",[]{reset();ready();start();check(events.back().depth==1,"snapshot applied unlocked");});
  add("fresh_ONE_second_renewal_runs_beyond_five_seconds",[]{reset();ready();start();for(int i=1;i<=10;++i){fakeMs=10000+i*1000;message(frame());check(lastGPIO()==HIGH,"IR renew interrupted");}fakeMs=25000;runTicks(1);check(lastGPIO()==LOW,"final lease failed to expire");});
  add("main_stall_independent_task_stops_after_five_seconds",[]{reset();ready();start();const size_t afterON=events.size();runTicks(301);uint32_t low=UINT32_MAX;for(size_t i=afterON;i<events.size();++i)if(events[i].kind=="gpio"&&events[i].value==LOW){low=events[i].at;break;}check(low==15000&&!irControl.on(),"independent task cutoff");});
  add("blocking_ack_publish_does_not_hold_IR_ON",[]{reset();ready();publishHook=[]{runTicks(301);};message(frame());check(!irControl.on()&&lastGPIO()==LOW,"blocked publish prevented cutoff");});
  add("WiFi_loss_stops_without_main_service",[]{reset();ready();start();WiFi.value=0;runTicks(1);check(!irControl.on()&&lastGPIO()==LOW,"WiFi fault");});
  add("MQTT_disconnect_service_commits_OFF",[]{reset();ready();start();mqtt.online=false;irService();check(!irControl.on()&&lastGPIO()==LOW,"MQTT fault");});
  add("half_open_socket_true_still_expires_without_renewal",[]{reset();ready();start();check(mqtt.connected(),"fixture socket");runTicks(251);check(lastGPIO()==LOW,"half open kept IR ON");});
  add("malformed_current_topic_fails_OFF",[]{reset();ready();start();message("bad");check(lastGPIO()==LOW&&!irControl.on(),"malformed frame did not fail OFF");});
  add("foreign_camera_pump_and_cage_topics_do_not_mutate_IR",[]{reset();ready();start();for(const char*t:{TOPIC_BASE "/r11/command/test",TOPIC_BASE "/camera/mode","habitat/v1/OTHER/ir/command/test"}){message("bad",t);check(lastGPIO()==HIGH&&irControl.on(),"foreign topic changed IR");}});
  add("duplicate_packet_does_not_extend_GPIO_deadline",[]{reset();ready();auto on=frame();message(on);fakeMs=14000;message(on);fakeMs=15000;runTicks(1);check(lastGPIO()==LOW&&!irControl.on(),"duplicate renewed IR");});
  add("new_nonce_reconnect_retires_old_packet",[]{reset();ready();auto old=frame();message(old);nonce="22222222-2222-4222-8222-222222222222";irConnected();check(lastGPIO()==LOW,"reconnect not OFF");message(old);check(!irControl.on()&&lastGPIO()==LOW,"old session replay");});
  add("subscribe_failure_locks_output_OFF",[]{reset();ready();start();mqtt.subscribeOk=false;irConnected();check(!irNetwork&&!irControl.on()&&lastGPIO()==LOW,"subscribe failure");});
  add("explicit_OFF_does_not_get_reasserted_by_task",[]{reset();ready();start();message(frame("off",0));runTicks(1);check(lastGPIO()==LOW&&!irControl.on(),"stale HIGH after OFF");});
  add("STOP_latch_cannot_be_renewed",[]{reset();ready();start();message(frame("stop",0,0));message(frame());check(lastGPIO()==LOW&&!irControl.on(),"STOP overridden");});
  add("heartbeat_rejected_without_renewal",[]{reset();ready();start();fakeMs=14000;message(frame("heartbeat",0,0));fakeMs=15000;runTicks(1);check(lastGPIO()==LOW,"heartbeat renewed IR");});
  add("status_and_ack_do_not_claim_optical_confirmation",[]{reset();ready();start();irService();for(const auto&p:mqtt.published){check(p.first.find("/ir/")!=std::string::npos,"wrong publication domain");check(p.second.find("\"actual_ir_on\":null")!=std::string::npos,"invented IR observation");}});
  add("twenty_task_phases_bound_GPIO_lease_stop",[]{for(unsigned phase=0;phase<20;++phase){reset();ready();start();const size_t afterON=events.size();fakeMs=10000+phase;runTicks(252);uint32_t low=UINT32_MAX;for(size_t i=afterON;i<events.size();++i)if(events[i].kind=="gpio"&&events[i].value==LOW){low=events[i].at;break;}check(low>=15000&&low<=15020,"phase lease bound missed");}});
#endif
  unsigned failed=0;std::cout<<"{\"suite\":\"IR-production-runtime-fake-Arduino-RTOS\",\"outputs_compile_enabled\":"<<(HABITAT_IR_OUTPUTS?"true":"false")<<",\"hardware_tested\":false,\"actual_RTOS_latency_tested\":false,\"cases\":[\n";
  for(size_t i=0;i<tests.size();++i){std::string error;try{tests[i].second();}catch(const std::exception&e){++failed;error=e.what();}std::cout<<"{\"name\":\""<<tests[i].first<<"\",\"passed\":"<<(error.empty()?"true":"false");if(!error.empty())std::cout<<",\"error\":\""<<error<<"\"";std::cout<<"}"<<(i+1<tests.size()?",\n":"\n");if(trace)for(const auto&e:events)trace<<tests[i].first<<','<<e.at<<','<<e.kind<<','<<e.pin<<','<<e.value<<','<<e.depth<<'\n';}
  std::cout<<"],\"total\":"<<tests.size()<<",\"failed\":"<<failed<<"}\n";return failed?1:0;
}
