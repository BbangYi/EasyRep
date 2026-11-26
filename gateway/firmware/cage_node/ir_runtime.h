#pragma once
#include "ir_controller.h"

static_assert(HABITAT_SHT_SDA_PIN==21 && HABITAT_SHT_SCL_PIN==22 &&
              HABITAT_T2_PIN==18 && HABITAT_T3_PIN==19,
              "IR GPIO4 profile is only for the reviewed CAGE001 30-pin wiring.");
static_assert(HABITAT_IR_OUTPUTS==0 || HABITAT_IR_OUTPUTS==1,"Invalid IR output lock.");
ir::Controller irControl(HABITAT_IR_OUTPUTS==1);
portMUX_TYPE irMux=portMUX_INITIALIZER_UNLOCKED;
bool irReady=false,irNetwork=false;
char irTopic[256]={};uint32_t irNextStatus=0;

uint64_t irUtc(){struct timeval v;gettimeofday(&v,nullptr);return uint64_t(v.tv_sec)*1000+uint64_t(v.tv_usec)/1000;}
// GPIO application stays in the same critical section as state changes.
void irApply(){gpio_set_level(gpio_num_t(ir::PIN),irControl.on()?HIGH:LOW);}
void irSafetyTask(void*){
  TickType_t wake=xTaskGetTickCount();
  for(;;){
    const bool wifi=WiFi.status()==WL_CONNECTED;
    portENTER_CRITICAL(&irMux);
    irControl.tick(millis(),irNetwork && wifi);irApply();
    portEXIT_CRITICAL(&irMux);
    vTaskDelayUntil(&wake,pdMS_TO_TICKS(ir::TICK_MS));
  }
}
void irSetup(){
  // Existing R3 10k pull-down covers reset/bootloader time before setup.
  gpio_set_level(gpio_num_t(ir::PIN),LOW);pinMode(ir::PIN,OUTPUT);
  irReady=xTaskCreatePinnedToCore(irSafetyTask,"cage-ir",3072,nullptr,3,nullptr,1)==pdPASS;
}
void irMessage(char *topic,uint8_t *data,unsigned int length){
  if(!irReady || strcmp(topic,irTopic))return;
  r15::Command command;
  if(!r15::parse(data,length,command,"IR/1")){
    portENTER_CRITICAL(&irMux);irControl.stop("invalid_command");irApply();portEXIT_CRITICAL(&irMux);
    Serial.println("IR invalid command; output OFF");return;
  }
  const bool wifi=WiFi.status()==WL_CONNECTED;
  const uint32_t at=millis();const uint64_t utc=irUtc();
  portENTER_CRITICAL(&irMux);
  irControl.tick(at,irNetwork && wifi);
  const char *reason=irControl.receive(command,utc,at);irApply();
  const bool requested=irControl.on();
  portEXIT_CRITICAL(&irMux);
  char reply[512];
  const int n=snprintf(reply,sizeof(reply),
    "{\"schema_version\":1,\"session_id\":\"%s\",\"command_id\":\"%s\",\"sequence\":%lu,"
    "\"reason\":\"%s\",\"gpio_requested_on\":%s,\"actual_ir_on\":null}",
    command.session,command.id,(unsigned long)command.sequence,reason,requested?"true":"false");
  if(n>0 && n<int(sizeof(reply)))mqtt.publish((String(TOPIC_BASE)+"/ir/ack").c_str(),reply,false);
}
void irConnected(){
  if(!irReady)return;
  const String nonce=uuid();
  const int n=snprintf(irTopic,sizeof(irTopic),"%s/ir/command/%s",TOPIC_BASE,nonce.c_str());
  if(n<=0 || n>=int(sizeof(irTopic))){
    portENTER_CRITICAL(&irMux);irControl.disconnect();irNetwork=false;irApply();portEXIT_CRITICAL(&irMux);return;
  }
  portENTER_CRITICAL(&irMux);irControl.connect(nonce.c_str());irNetwork=true;irApply();portEXIT_CRITICAL(&irMux);
  if(!mqtt.subscribe(irTopic,1)){
    portENTER_CRITICAL(&irMux);irControl.disconnect();irNetwork=false;irApply();portEXIT_CRITICAL(&irMux);
  }
  irNextStatus=0;
}
void irService(){
  if(!irReady)return;
  const bool network=mqtt.connected() && WiFi.status()==WL_CONNECTED;
  const uint32_t at=millis();
  portENTER_CRITICAL(&irMux);
  if(!network)irControl.disconnect();
  irNetwork=network;irControl.tick(at,network);irApply();
  portEXIT_CRITICAL(&irMux);
  if(!network || (int32_t)(at-irNextStatus)<0)return;
  irNextStatus=at+500;
  char session[37];const char *reason;bool on;
  portENTER_CRITICAL(&irMux);
  memcpy(session,irControl.session(),37);reason=irControl.reason();on=irControl.on();
  portEXIT_CRITICAL(&irMux);
  if(!session[0])return;
  char body[768];
  const int n=snprintf(body,sizeof(body),
    "{\"schema_version\":1,\"session_id\":\"%s\",\"command_topic\":\"%s\","
    "\"outputs_locked\":%s,\"gpio_requested_on\":%s,\"reason\":\"%s\","
    "\"actual_ir_on\":null,\"max_lease_ms\":5000}",
    session,irTopic,HABITAT_IR_OUTPUTS==1?"false":"true",on?"true":"false",reason);
  if(n>0 && n<int(sizeof(body)))mqtt.publish((String(TOPIC_BASE)+"/ir/hello").c_str(),body,false);
}
