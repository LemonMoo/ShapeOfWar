## v0.3.8_2 - Stop Re-Uploading the Map Texture Every Frame

- The GPU flat map was re-uploading its whole terrain texture to the graphics card on every single frame, even while nothing changed -- now only does it when the map actually needs it.
