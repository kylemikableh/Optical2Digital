import cv2 as cv
img = cv.imread("input\extrailer\extrailer4.jpeg", cv.IMREAD_UNCHANGED)

scale_percent = 25 # percent of original size
width = int(img.shape[1] * scale_percent / 100)
height = int(img.shape[0] * scale_percent / 100)
dim = (width, height)

# resize image
resized = cv.resize(img, dim, interpolation = cv.INTER_AREA)


cv.imshow("Display window", resized)
k = cv.waitKey(0) # Wait for a keystroke in the window