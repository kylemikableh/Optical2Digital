import cv2 as cv2
import pandas as pd
import lib.optical_decoder as opt
import numpy as np

INPUT_FOLDER = "./input/DolbyStereo/"
FRAMES_PER_SECOND = 24
CUTTOFF_FREQUENCY = 16000
S_INT16_MAX = 32767
STEREO_TRACKS = True

DEBUG_SHOW = True

# Pull images files
filenames = opt.get_imgs_range(INPUT_FOLDER, 0, 11600)
duration_in_seconds = len(filenames) / FRAMES_PER_SECOND
img_height = 0

images = []
for filename in filenames:
    img = cv2.imread(INPUT_FOLDER + filename, cv2.IMREAD_GRAYSCALE) # Read in image as greyscale
    img = opt.crop_img_left_right(img, 100, 85)
    
    # if DEBUG_SHOW:
    #     opt.disp_img_with_scale(img, 0.5)
    #     break

    ret,threshold = cv2.threshold(img,128,255,cv2.THRESH_BINARY) # invert so white = 255, black = 0
    images.append(threshold) # Add to list of filtered images our image
    height,width = img.shape
    img_height = height

images = images[::-1] # Reverse the list order to get the expected order of the optical tracks
print(img_height)

# Concatinated image to show merge visually
# if DEBUG_SHOW:
#     merged_images = cv2.vconcat(images[0:2])
#     opt.disp_img_with_scale(merged_images, 0.5)
#     cv2.imwrite("mergedDemo.jpeg",merged_images)

# Process each image
mean_values_arr = []
img_count = 0
for img in images:

    if STEREO_TRACKS:
        left_img,right_img = opt.get_left_right_imgs(img, 115)
        left_mean, right_mean = opt.process_stereo_mean(left_img, right_img)
        mean_tuples = (left_mean, right_mean)
        mean_values_arr.append(mean_tuples)
        # cv2.imwrite(f"output\\output{ img_count }_left.jpeg", left_img)
        # cv2.imwrite(f"output\\output{ img_count }_right.jpeg", right_img)
    else:
        mean = opt.process_mono_mean(img)
        mean_values_arr.append(mean)
        cv2.imwrite(f"output\\output{ img_count }.jpeg", img)
    
    img_count += 1

mean_values_arr = mean_values_arr[::-1]
print(mean_values_arr)

if not STEREO_TRACKS:
    opt.write_wav_mono(mean_values_arr, img_height, duration_in_seconds, FRAMES_PER_SECOND, "outputnew.wav")
else:
    opt.write_wav_stereo(mean_values_arr, img_height, duration_in_seconds, FRAMES_PER_SECOND, "outputnew.wav")
