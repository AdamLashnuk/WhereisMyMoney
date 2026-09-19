import os
from ai.receipt import categorize_receipt

script_dir = os.path.dirname(os.path.abspath(__file__))
image_path = os.path.join(script_dir, "sample_receipt.jpg")

result = categorize_receipt(image_path)
print(result)