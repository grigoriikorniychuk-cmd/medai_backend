from app.settings.auth import evenlabs

client = evenlabs()

audio = client.generate(
    text="Hello, how are you?",
    voice="Bella",
)

with open("audio.mp3", "wb") as f:
    f.write(audio)

print("Audio saved to audio.mp3")