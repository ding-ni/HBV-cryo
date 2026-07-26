# -*- coding: utf-8 -*-
"""Build-time package variant.

Source and project-delivery builds default to the dated project license. The
installer builder overwrites this file only inside its staging directory when
creating the owner's unlimited local package.
"""

LICENSE_MODE = "project"
