# test_tux.py
spot_sample = "Estado: playing | Canción: The Edge Of Everything | Artista: ryman leon"

estado_audio = "inactivo"
cancion_actual = ""

if "playing" in spot_sample.lower():
    for parte in spot_sample.split("|"):
        p = parte.strip()
        if p.lower().startswith("canción:") or p.lower().startswith("cancion:"):
            cancion_actual = p.split(":", 1)[1].strip()
        elif p.lower().startswith("artista:"):
            art = p.split(":", 1)[1].strip()
            if cancion_actual and art:
                cancion_actual = f"{cancion_actual} - {art}"
    estado_audio = cancion_actual if cancion_actual else "Reproduciendo"

print("Parsed estado_audio:", estado_audio)
print("Emotion would be: music")
