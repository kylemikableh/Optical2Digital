import cv2
import natsort
import os
import numpy as np
import wave
import struct

S_INT16_MAX = 32767
BIT_DEPTH = 16

def get_imgs_range(imgs_path: str, start: int, end: int) -> list:
    '''
    Get images in a range from folder
    '''
    imagefiles = natsort.natsorted(os.listdir(imgs_path))
    imagefiles = imagefiles[start:end]
    return imagefiles

def crop_img_left_right(img, left: int, right: int):
    '''
    Crop the image from left and right by the provided pixels
    Trims by number, so right 50 takes 50 off the right
    '''
    height,width = img.shape
    ret_img = img[0:height,left:width-right]
    return ret_img

def disp_img_with_scale(img, scale_factor: float):
    '''(
    Display the image prvided, at a reduced scale.
    '''
    resized_image = cv2.resize(img, None, fx=scale_factor, fy=scale_factor)
    cv2.imshow("Crop Example", resized_image)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

def get_left_right_imgs(img, center_pos: int):
    '''
    Get the left/right audio tracks as seperate images
    '''
    height,width = img.shape
    img_left = img[0:height,0:center_pos]
    img_right = img[0:height,center_pos:width]
    return (img_left, img_right)

def process_mono_mean(img):
    '''
    '''
    # Get mean value per row (0-255)
    mean_values = np.mean(img, axis=1)
    # Need to get values 0-255 to 0-1 (1 = white, 0 = black)
    mean_values = mean_values / 255.0
    # Now get the converted values to sint_16 values (–32768 to 32767)\n",
    # Ill make this cleaner and more constanants in the future\n",
    mean_values = mean_values * S_INT16_MAX
    mean_values = mean_values.astype(int)
    mean_values = mean_values - (int(S_INT16_MAX // 2))
    return mean_values

def process_stereo_mean(left_img, right_img):
    '''
    '''
    left_mean = process_mono_mean(left_img)
    right_mean = process_mono_mean(right_img)
    return left_mean, right_mean

def write_wav_mono(mono_samples, img_height, duration, fps:int, raw_output_file: str):
    '''
    Write the wave mono samples
    '''
    sample_rate = img_height * fps # Currently making the sample rate the height of each image times the amount of frames in a second
    print(f"Sample rate: { sample_rate }")
    num_channels = 1 # MONO
    num_frames = int(sample_rate * duration) # amount of frames in a second

    with wave.open(raw_output_file, 'wb') as output_file:
        output_file.setnchannels(num_channels)
        output_file.setsampwidth(BIT_DEPTH // 8)
        output_file.setframerate(sample_rate)
        output_file.setnframes(num_frames)
        output_file.setcomptype('NONE', 'Not Compressed')
        
        data = b''
        for sample in mono_samples:
             for i in range(0,img_height):
                # print(sample[i])
                packed_sample = struct.pack('<h', sample[i])
                data += packed_sample
        output_file.writeframesraw(data)
