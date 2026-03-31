# Optical Audio to Digital WAV
Optical audio on film has been a critical part of the presentation of motion pictures since the 1920s when variable-area/variable-density was first introduced.
Converting scans of film can be difficult, and extracting audio moreso. There has been a very good tool for the past decade, [AEO-Light](https://github.com/usc-imi/aeo-light), that is popular 
to use to convert the audio. However, the codebase is in C++, and it is difficult to understand how it works, and to add new features to. As a result, this project is to create a modern 
Optical to Digital conversion tool, written in python, that can convert optical audio of all shapes and sizes (possibly other formats too like Dolby-Digital or SDDS) and Dolby A/SR easily and effectivly.
Also, another important goal is that anyone can understand how the audio conversions work and can extend the functionality into their own projects too.

## Useful Links
* Sound-on-film https://en.wikipedia.org/wiki/Sound-on-film
* Dolby Stereo https://en.wikipedia.org/wiki/Dolby_Stereo
* Dolby SR https://en.wikipedia.org/wiki/Dolby_SR
* Dolby Digital https://en.wikipedia.org/wiki/Dolby_Digital

# Progress
A basic web-based application now exists that converts individual images that contain Optical Audio to a .wav that is subsequently downloaded. More features are being added. Also, the `KylesOpticalDecoder.py` can be used standalone in CLI, allowing for other programs/scripting to run it in a pipeline.

## Kyle's Optical Decoder
Python CLI tool that can extract film optical audio

To run application in UI mode:
`python server.py`
`cd frontend && npm run dev`

## Theory of Operation
TODO

### Contributors
* Kyle Mikolajczyk
* Will Dirkschka
* Ben Peters
* Thomas Piccicone (35mm Scan Examples)