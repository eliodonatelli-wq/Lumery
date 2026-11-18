"""Independent verbatim copy of the Stretch 22 luminance helper."""
def luma(image):
    if image.ndim == 2:
        return image
    return (image[..., 0] * .2126 + image[..., 1] * .7152
            + image[..., 2] * .0722)[..., None]

