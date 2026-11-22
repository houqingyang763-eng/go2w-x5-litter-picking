"""Build the inference module from the pinned SuperGradients release wheel."""

import argparse
import ast
import hashlib
from pathlib import Path
import zipfile


SUPER_GRADIENTS_SHA256 = "f4ebf2f551399f77070609da15efb2cfaf90392a38be4be8b1d4eab0d9c47381"
MODULE_PREFIX = "super_gradients/training/"
DDRNET_DEFINITIONS = (
    "ConvBN", "_make_layer", "DAPPMBranch", "DAPPM", "SegmentHead", "UpscaleOnline",
    "DDRBackBoneBase", "BasicDDRBackBone", "DDRNet", "DDRNetCustom",
    "DEFAULT_DDRNET_23_PARAMS", "DEFAULT_DDRNET_39_PARAMS", "DDRNet39",
)
HEADER = '''"""Inference adaptation of SuperGradients 3.7.1 and its DDRNet implementation.

See SUPER_GRADIENTS_LICENSE.md for the license supplied with the release.
"""

import warnings
from abc import ABC
from collections import OrderedDict
from types import SimpleNamespace
from typing import Callable, Dict, Optional

import torch
from torch import nn
from torch.nn import functional as F


class HpmStruct(SimpleNamespace):
    def override(self, **parameters):
        vars(self).update(parameters)

    def to_dict(self):
        return vars(self).copy()


def get_param(parameters, name):
    return getattr(parameters, name, None)
'''


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def definitions(source, names, nodes=None):
    if nodes is None:
        nodes = ast.parse(source).body
    matches = {}
    lines = source.splitlines()
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            name = node.name
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        else:
            continue
        if name in names:
            matches[name] = "\n".join(lines[node.lineno - 1:node.end_lineno])
    return "\n\n\n".join(matches[name] for name in names)


def build_module(wheel, output):
    if file_sha256(wheel) != SUPER_GRADIENTS_SHA256:
        raise ValueError("SuperGradients wheel does not match the verified 3.7.1 release.")
    with zipfile.ZipFile(wheel) as archive:
        regularization = archive.read(MODULE_PREFIX + "utils/regularization_utils.py").decode("utf-8")
        resnet = archive.read(MODULE_PREFIX + "models/classification_models/resnet.py").decode("utf-8")
        segmentation = archive.read(MODULE_PREFIX + "models/segmentation_models/segmentation_module.py").decode("utf-8")
        ddrnet = archive.read(MODULE_PREFIX + "models/segmentation_models/ddrnet.py").decode("utf-8")
        license_text = archive.read("super_gradients-3.7.1.dist-info/LICENSE.md")
    base = next(node for node in ast.parse(segmentation).body
                if isinstance(node, ast.ClassDef) and node.name == "SegmentationModule")
    initializer = definitions(segmentation, ("init_params",), base.body)
    layers = definitions(ddrnet, DDRNET_DEFINITIONS)
    layers = layers.replace("nn.Module, SupportsReplaceInputChannels, ABC", "nn.Module, ABC")
    layers = layers.replace("SegmentationModule, ExportableSegmentationModel", "nn.Module")
    layers = layers.replace("super().__init__(use_aux_heads=use_aux_heads)", "super().__init__()", 1)
    marker = "\n\n\nclass DDRNetCustom(DDRNet):"
    layers = layers.replace(marker, "\n\n" + initializer + marker, 1)
    code = "\n\n\n".join((
        HEADER.rstrip(),
        definitions(regularization, ("drop_path", "DropPath")),
        definitions(resnet, ("BasicResNetBlock", "Bottleneck")),
        layers,
    )) + "\n"
    compile(code, str(output), "exec")
    output.write_bytes(code.encode("utf-8"))
    output.with_name("SUPER_GRADIENTS_LICENSE.md").write_bytes(license_text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build_module(args.wheel, args.output)
