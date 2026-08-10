#include "udp_microphone.h"

#include "esphome/core/hal.h"
#include "esphome/core/log.h"

#include <algorithm>
#include <cerrno>
#include <cstring>

namespace esphome::udp_microphone {

static const char *const TAG = "udp_microphone";
static constexpr uint32_t LEASE_MS = 5000;
static constexpr size_t MAX_DATAGRAM = 1200;

void UdpMicrophone::setup() {
  this->socket_ = socket::socket(AF_INET, SOCK_DGRAM, IPPROTO_IP);
  if (this->socket_ == nullptr || this->socket_->setblocking(false) != 0) {
    ESP_LOGE(TAG, "Unable to create UDP socket");
    this->mark_failed();
    return;
  }

  struct sockaddr_storage listen_address {};
  // The Voice PE enables IPv6, but this control protocol intentionally uses an
  // IPv4 socket to match the Docker host adapter. set_sockaddr_any() would select
  // an IPv6 address whenever IPv6 is compiled in.
  const socklen_t listen_len = socket::set_sockaddr(reinterpret_cast<struct sockaddr *>(&listen_address),
                                                    sizeof(listen_address), "0.0.0.0", this->port_);
  if (listen_len == 0 ||
      this->socket_->bind(reinterpret_cast<struct sockaddr *>(&listen_address), listen_len) != 0) {
    ESP_LOGE(TAG, "Unable to bind UDP port %u: errno %d", this->port_, errno);
    this->mark_failed();
    return;
  }

  this->microphone_->add_data_callback([this](const std::vector<uint8_t> &data) { this->on_audio_(data); });
}

bool UdpMicrophone::lease_active_() const {
  return this->client_len_ != 0 && static_cast<int32_t>(this->lease_until_ - millis()) > 0;
}

void UdpMicrophone::loop() {
  if (this->socket_ == nullptr)
    return;

  char request[160];
  while (true) {
    struct sockaddr_storage peer {};
    socklen_t peer_len = sizeof(peer);
    const ssize_t received = this->socket_->recvfrom(request, sizeof(request) - 1,
                                                     reinterpret_cast<struct sockaddr *>(&peer), &peer_len);
    if (received < 0) {
      if (errno != EAGAIN && errno != EWOULDBLOCK)
        ESP_LOGW(TAG, "UDP receive failed: errno %d", errno);
      break;
    }
    request[received] = '\0';

    const std::string start = "START " + this->token_;
    const std::string stop = "STOP " + this->token_;
    if (start == request) {
      std::memcpy(&this->client_, &peer, peer_len);
      this->client_len_ = peer_len;
      this->lease_until_ = millis() + LEASE_MS;
    } else if (stop == request && this->client_len_ == peer_len &&
               std::memcmp(&this->client_, &peer, peer_len) == 0) {
      this->client_len_ = 0;
    }
  }

  if (!this->lease_active_())
    this->client_len_ = 0;
}

void UdpMicrophone::on_audio_(const std::vector<uint8_t> &data) {
  if (!this->lease_active_() || this->socket_ == nullptr)
    return;

  for (size_t offset = 0; offset < data.size(); offset += MAX_DATAGRAM) {
    const size_t length = std::min(MAX_DATAGRAM, data.size() - offset);
    this->socket_->sendto(data.data() + offset, length, 0, reinterpret_cast<struct sockaddr *>(&this->client_),
                          this->client_len_);
  }
}

void UdpMicrophone::dump_config() {
  ESP_LOGCONFIG(TAG, "Voice PE intercom microphone:");
  ESP_LOGCONFIG(TAG, "  Control port: %u", this->port_);
  ESP_LOGCONFIG(TAG, "  Format: signed 16-bit little-endian PCM from configured microphone source");
  ESP_LOGCONFIG(TAG, "  Lease duration: %u ms", LEASE_MS);
}

}  // namespace esphome::udp_microphone
