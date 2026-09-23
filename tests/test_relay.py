from telegram_source import relay


def test_build_text_con_remitente(monkeypatch):
    monkeypatch.setattr(relay, "SHOW_SENDER", True)
    assert relay.build_text("Ana", " hola ") == "Ana: hola"
    assert relay.build_text("Ana", None) == "Ana:"


def test_build_text_sin_remitente(monkeypatch):
    monkeypatch.setattr(relay, "SHOW_SENDER", False)
    assert relay.build_text("Ana", "hola") == "hola"


MENSAJE = (
    "📈 ROI 4.65%\n"
    "🏠 Winamax\n"
    "💵 Cuota @2.5\n"
    "\n"
    "🔎 Consejo: Revisad otras casas por si aparece una combinación con mayor rentabilidad."
)


def test_rewrite_tip_sin_configurar_deja_el_texto():
    assert relay.rewrite_tip(MENSAJE, None) == MENSAJE


def test_rewrite_tip_sustituye_la_linea():
    out = relay.rewrite_tip(MENSAJE, "💡 Compara cuotas en otras casas")
    assert out.splitlines()[-1] == "💡 Compara cuotas en otras casas"
    assert "Consejo" not in out and out.startswith("📈 ROI 4.65%")


def test_rewrite_tip_vacio_la_quita():
    out = relay.rewrite_tip(MENSAJE, "")
    assert out == "📈 ROI 4.65%\n🏠 Winamax\n💵 Cuota @2.5"


def test_build_text_aplica_el_cambio_del_consejo(monkeypatch):
    monkeypatch.setattr(relay, "SHOW_SENDER", False)
    monkeypatch.setattr(relay, "TIP_TEXT", "")
    assert "Consejo" not in relay.build_text(None, MENSAJE)


def test_pick_source_numerico_o_titulo():
    assert relay._pick_source("-1001234567890") == -1001234567890
    assert relay._pick_source("Mi grupo") == "Mi grupo"


def test_topic_id_of():
    from types import SimpleNamespace as NS

    assert relay.topic_id_of(NS(reply_to=None)) == 1
    assert relay.topic_id_of(NS(reply_to=NS(forum_topic=False, reply_to_top_id=None, reply_to_msg_id=9))) == 1
    # primer mensaje del tema: reply_to_msg_id es el id del tema
    assert relay.topic_id_of(NS(reply_to=NS(forum_topic=True, reply_to_top_id=None, reply_to_msg_id=42))) == 42
    # respuesta dentro del tema: reply_to_top_id es el tema
    assert relay.topic_id_of(NS(reply_to=NS(forum_topic=True, reply_to_top_id=42, reply_to_msg_id=77))) == 42


def test_should_relay_lista_de_permitidos():
    only = {"6", "bwin"}
    assert relay.should_relay(6, None, only, set())
    assert relay.should_relay(9, "Bwin", only, set())
    assert not relay.should_relay(9, "Otro", only, set())
    assert not relay.should_relay(1, None, only, {"1"})


def test_should_relay_lista_de_excluidos():
    skip = {"5", "avisos"}
    assert not relay.should_relay(5, None, set(), skip)
    assert not relay.should_relay(9, "Avisos", set(), skip)
    assert relay.should_relay(9, "Futbol", set(), skip)


def test_needs_name():
    assert not relay._needs_name({"1", "2"}, set())
    assert relay._needs_name({"1", "bwin"})
