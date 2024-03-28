# Proof of Concept SVA Optical Audio to Digital WAV
Optical audio on film has been a critical part of the presentation of motion pictures since the 1920s when variable-area/variable-density was first introduced.
Converting scans of film can be difficult, and extracting audio moreso. There has been a very good tool for the past decade, [AEO-Light](https://github.com/usc-imi/aeo-light), that is popular 
to use to convert the audio. However, the codebase is in C++, and it is difficult to understand how it works, and to add new features to. As a result, this project is to create a modern 
Optical to Digital conversion tool, written in python, that can convert optical audio of all shapes and sizes (possibly other formats too like Dolby-Digital or SDDS) and Dolby A/SR easily and effectivly.
Also, another important goal is that anyone can understand how the audio conversions work and can extend the functionality into their own projects too.

For now, the focus is proof of concept to get acceptable audio out of images, that can then be extended into a full tool.

## Useful Links
* Sound-on-film https://en.wikipedia.org/wiki/Sound-on-film
* Dolby Stereo https://en.wikipedia.org/wiki/Dolby_Stereo
* Dolby SR https://en.wikipedia.org/wiki/Dolby_SR
* Dolby Digital https://en.wikipedia.org/wiki/Dolby_Digital


## Setup (Windows)
1) Make a python environment
2) Activate `.\venv\Scripts\Activate.ps1`
3) Install dependencies `pip install -r requirements.txt`
4) Start noteboox `jupyter notebook`

### Contributors
* Kyle Mikolajczyk
* Will Dirkschka
* Ben Peters
* Thomas Piccicone (35mm Scan Examples)