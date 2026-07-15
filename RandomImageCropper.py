from PIL import Image
import random
import os

class RandomImageCropper:
    def __init__(self, input_image_path, output_folder, num_crops=100,
                 crop_width=1011, crop_height=638):
        # Initialize the parameters for cropping
        self.input_image_path = input_image_path
        self.output_folder = output_folder
        self.num_crops = num_crops
        self.crop_width = crop_width
        self.crop_height = crop_height
        self.image = None
        self.width = None
        self.height = None
        self.cropped_areas = []  # To track cropped regions, optional for overlap control

        # Load the image
        self.load_image()

    def load_image(self):
        """Load the image and get its dimensions."""
        self.image = Image.open(self.input_image_path)
        self.width, self.height = self.image.size

    def random_crop(self):
        """Generate a random crop of fixed credit card size."""
        # Ensure the crop fits within the image boundaries
        left = random.randint(0, self.width - self.crop_width)
        top = random.randint(0, self.height - self.crop_height)

        right = left + self.crop_width
        bottom = top + self.crop_height

        # Optional: Skip if the crop area overlaps with an existing crop
        if (left, top, right, bottom) in self.cropped_areas:
            return None

        # Add the crop area to the list to avoid overlap in the future
        self.cropped_areas.append((left, top, right, bottom))

        return self.image.crop((left, top, right, bottom))

    def save_crop(self, cropped_image, crop_index):
        """Save the cropped image to the output folder."""
        os.makedirs(self.output_folder, exist_ok=True)
        cropped_image.save(os.path.join(self.output_folder, f'cropped_image_{crop_index}.jpg'))

    def generate_crops(self, cquantity=None):
        """Generate the specified number of random crops and save them."""
        for i in range(1, self.num_crops + 1):
            cropped_image = self.random_crop()
            if cropped_image:
                self.save_crop(cropped_image, i)
            else:
                print(f"Skipping duplicate crop for index {i}.")
        print(f"{self.num_crops} cropped images have been saved in the folder '{self.output_folder}'.")

    def get_croped_image(self, id):
        cropped_image = self.random_crop()
        if cropped_image:
            self.save_crop(cropped_image, id)
        else:
            print(f"Skipping duplicate crop for index {i}.")

# Example usage:
if __name__ == "__main__":
    # Define your input image and output folder
    input_image_path = 'media/Marta Banaszek - Obraz II.jpg'
    output_folder = 'media/cropped_images'

    # Initialize the RandomImageCropper class
    cropper = RandomImageCropper(input_image_path, output_folder)

    # Generate and save the random crops
    for i in range(401, 601):
        cropper.get_croped_image(i)
