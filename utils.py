import os
import sys

import torch
import importlib
import shutil
import logging
import cv2
import PIL
import io
import pickle
import random
import numpy as np
import json


def save_json(obj, file_path):
    with open(file_path, 'w') as f:
        json.dump(json.dumps(obj), f)


def load_json(file_path):
    with open(file_path, 'r') as f:
        return json.loads(json.load(f))


def save(obj, file_path):
    print('saving to {}'.format(file_path))
    with open(file_path, 'wb') as f:
        pickle.dump(obj, f)


def load(file_path):
    with open(file_path, 'rb') as f:
        obj = pickle.load(f)
    return obj


def convert_img_to_rgb(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def convert_img_to_bytes(img):
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    im_out = PIL.Image.fromarray(img)
    f = io.BytesIO()
    im_out.save(f, format='png')
    return f.getvalue()


def video_iter(file_path):
    video = cv2.VideoCapture(file_path)

    success, image = video.read()

    if success:
        yield image

    while success:
        success, image = video.read()
        if success:
            yield image


def set_seed(seed):
    random.seed(seed)
    os.environ['PYTHONHASHSEED'] = str(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.backends.cudnn.deterministic = True

