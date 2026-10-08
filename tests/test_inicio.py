def test_inicio_responde_y_muestra_nombre(client):
    respuesta = client.get("/")
    assert respuesta.status_code == 200
    assert "Agenda Psi" in respuesta.get_data(as_text=True)
