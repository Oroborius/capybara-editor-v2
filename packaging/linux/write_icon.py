"""Write the 256x256 capybara icon (held as base64 in src/mxl_app_icon.py) as a PNG: write_icon.py <src dir> <out.png>"""
import base64, sys
sys.path.insert(0, sys.argv[1])
import mxl_app_icon

with open(sys.argv[2], 'wb') as f:
    f.write(base64.b64decode(mxl_app_icon.ICONS[0]))
