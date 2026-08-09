#pragma once

#include "esphome/components/microphone/microphone_source.h"
#include "esphome/components/socket/socket.h"
#include "esphome/core/component.h"

#include <cstdint>
#include <memory>
#include <string>

namespace esphome::udp_microphone {

class UdpMicrophone : public Component {
 public:
  explicit UdpMicrophone(microphone::MicrophoneSource *microphone) : microphone_(microphone) {}

  void setup() override;
  void loop() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::AFTER_CONNECTION; }

  void set_port(uint16_t port) { this->port_ = port; }
  void set_token(const std::string &token) { this->token_ = token; }

 protected:
  void on_audio_(const std::vector<uint8_t> &data);
  bool lease_active_() const;

  microphone::MicrophoneSource *microphone_;
  std::unique_ptr<socket::Socket> socket_;
  uint16_t port_{18555};
  std::string token_;
  struct sockaddr_storage client_ {};
  socklen_t client_len_{0};
  uint32_t lease_until_{0};
};

}  // namespace esphome::udp_microphone
