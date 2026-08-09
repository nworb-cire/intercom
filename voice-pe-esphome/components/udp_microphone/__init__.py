import esphome.codegen as cg
from esphome.components import microphone
import esphome.config_validation as cv
from esphome.const import CONF_ID, CONF_MICROPHONE, CONF_PORT


AUTO_LOAD = ["socket"]
DEPENDENCIES = ["microphone", "network"]

CONF_TOKEN = "token"

udp_microphone_ns = cg.esphome_ns.namespace("udp_microphone")
UdpMicrophone = udp_microphone_ns.class_("UdpMicrophone", cg.Component)

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(UdpMicrophone),
        cv.Required(CONF_MICROPHONE): microphone.microphone_source_schema(
            min_bits_per_sample=16,
            max_bits_per_sample=16,
            min_channels=1,
            max_channels=1,
        ),
        cv.Optional(CONF_PORT, default=18555): cv.port,
        cv.Required(CONF_TOKEN): cv.All(cv.string_strict, cv.Length(min=24, max=128)),
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    mic_source = await microphone.microphone_source_to_code(
        config[CONF_MICROPHONE], passive=True
    )
    var = cg.new_Pvariable(config[CONF_ID], mic_source)
    await cg.register_component(var, config)
    cg.add(var.set_port(config[CONF_PORT]))
    cg.add(var.set_token(config[CONF_TOKEN]))
