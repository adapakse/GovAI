#!/bin/sh
# Ręczne pobranie modelu Bielik do kontenera Ollama i nadanie aliasu
# zgodnego z rejestrem providerów GovAI ('bielik-11b-v2.3-instruct').
#
# Użycie (z hosta):
#   docker compose exec ollama sh /pull-bielik.sh
# lub bez montowania — wklej treść do:
#   docker compose exec ollama sh -c '...'
#
# Zmienne (opcjonalne):
#   MODEL_ALIAS  — nazwa docelowa widziana przez gateway (domyślnie bielik-11b-v2.3-instruct)
#   MODEL_SRC    — źródło na HuggingFace (domyślnie Bielik-4.5B v3.0 Q8_0, ~4.8 GB —
#                  to repozytorium GGUF ma tylko fp16 i Q8_0, brak Q4_K_M)
#
# Większy model (lepsza jakość, wolniejszy na CPU):
#   MODEL_SRC=hf.co/speakleash/Bielik-11B-v2.3-Instruct-GGUF:Q4_K_M \
#   MODEL_ALIAS=bielik-11b-v2.3-instruct sh pull-bielik.sh
set -e

MODEL_ALIAS="${MODEL_ALIAS:-bielik-11b-v2.3-instruct}"
MODEL_SRC="${MODEL_SRC:-hf.co/speakleash/Bielik-4.5B-v3.0-Instruct-GGUF:Q8_0}"

if ollama list | grep -q "$MODEL_ALIAS"; then
  echo "Model $MODEL_ALIAS już istnieje — pomijam pobieranie."
  exit 0
fi

echo "Pobieram $MODEL_SRC (może potrwać kilka–kilkanaście minut)..."
ollama pull "$MODEL_SRC"

echo "Tworzę alias $MODEL_ALIAS..."
ollama cp "$MODEL_SRC" "$MODEL_ALIAS"

echo "Gotowe. Dostępne modele:"
ollama list
