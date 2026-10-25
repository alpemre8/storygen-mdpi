"""Read GGUF tensor metadata without loading a model or adding dependencies.

Only single-file little-endian GGUF v3 is qualified by E01A. Tensor spans are
checked against the file, so metadata-only files and truncated shards fail.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import math
from pathlib import Path
import struct


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


# GGML types from llama.cpp gguf-py/gguf/constants.py. Other types fail closed.
TYPES = {0: ("F32", 1, 4), 1: ("F16", 1, 2), 2: ("Q4_0", 32, 18),
         3: ("Q4_1", 32, 20), 6: ("Q5_0", 32, 22), 7: ("Q5_1", 32, 24),
         8: ("Q8_0", 32, 34), 9: ("Q8_1", 32, 40), 10: ("Q2_K", 256, 84),
         11: ("Q3_K", 256, 110), 12: ("Q4_K", 256, 144),
         13: ("Q5_K", 256, 176), 14: ("Q6_K", 256, 210),
         15: ("Q8_K", 256, 292), 30: ("BF16", 1, 2)}
SCALARS = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i",
           6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}


def inspect_gguf(path: str | Path, *, hash_file: bool = True) -> dict:
    path = Path(path).resolve()
    size = path.stat().st_size
    with path.open("rb") as stream:
        def unpack(fmt):
            n = struct.calcsize("<" + fmt)
            data = stream.read(n)
            if len(data) != n:
                raise ValueError("Truncated GGUF metadata")
            return struct.unpack("<" + fmt, data)[0]

        def string():
            n = unpack("Q")
            if n > 16 * 1024 * 1024 or stream.tell() + n > size:
                raise ValueError("Invalid GGUF string length")
            return stream.read(n).decode("utf-8")

        def value(kind, depth=0):
            if depth > 2:
                raise ValueError("Nested GGUF array unsupported")
            if kind in SCALARS:
                return unpack(SCALARS[kind])
            if kind == 8:
                return string()
            if kind == 9:
                element, count = unpack("I"), unpack("Q")
                if count > 2000000:
                    raise ValueError("GGUF array limit exceeded")
                for _ in range(count):
                    value(element, depth + 1)
                return {"element_type": element, "count": count}
            raise ValueError(f"Unknown GGUF metadata type: {kind}")

        if stream.read(4) != b"GGUF" or unpack("I") != 3:
            raise ValueError("Single-file little-endian GGUF v3 required")
        count, kv_count = unpack("Q"), unpack("Q")
        if not 0 < count <= 1000000 or kv_count > 100000:
            raise ValueError("Invalid GGUF tensor/metadata count")
        metadata = {}
        for _ in range(kv_count):
            key = string()
            if key in metadata:
                raise ValueError("Duplicate GGUF metadata key")
            metadata[key] = value(unpack("I"))
        alignment = metadata.get("general.alignment", 32)
        if not isinstance(alignment, int) or alignment < 1 or alignment > 4096:
            raise ValueError("Invalid GGUF alignment")
        tensors, names = [], set()
        for _ in range(count):
            name, rank = string(), unpack("I")
            if name in names or not 1 <= rank <= 4:
                raise ValueError("Duplicate tensor or invalid dimensions")
            names.add(name)
            shape = [unpack("Q") for _ in range(rank)]
            if any(n == 0 for n in shape):
                raise ValueError("Empty tensor")
            kind, offset = unpack("I"), unpack("Q")
            if kind not in TYPES:
                raise ValueError(f"Unsupported tensor type {kind}; cannot qualify precision")
            dtype, block, nbytes = TYPES[kind]
            elements = math.prod(shape)
            if shape[0] % block or offset % alignment:
                raise ValueError("Invalid tensor block/alignment")
            tensors.append({"name": name, "shape": shape, "dtype": dtype,
                            "offset": offset, "bytes": elements // block * nbytes})
        data_start = (stream.tell() + alignment - 1) // alignment * alignment
    last = 0
    for tensor in sorted(tensors, key=lambda t: t["offset"]):
        if tensor["offset"] < last:
            raise ValueError("Overlapping tensor spans")
        last = tensor["offset"] + tensor["bytes"]
        if data_start + last > size:
            raise ValueError("Truncated GGUF tensor payload")
    if metadata.get("split.count", 1) != 1:
        raise ValueError("Split GGUF requires a separate completeness contract")
    return {"path": str(path), "size_bytes": size, "complete": True,
            "sha256": file_sha256(path) if hash_file else None,
            "metadata": metadata, "tensor_count": count,
            "tensor_types": dict(Counter(t["dtype"] for t in tensors)),
            "tensor_bytes": sum(t["bytes"] for t in tensors), "tensors": tensors}


def require_fp16(evidence: dict, *, family: str, model_id: str) -> None:
    tensors = evidence["tensors"]
    if not evidence.get("complete") or not any(t["dtype"] == "F16" for t in tensors):
        raise ValueError("Complete F16 checkpoint required")
    # llama.cpp F16 conversions retain one-dimensional norms/biases as F32.
    if any(t["dtype"] not in {"F16", "F32"} or
           (t["dtype"] == "F32" and len(t["shape"]) != 1) for t in tensors):
        raise ValueError("FP16 role rejects quantized/BF16/F32 matrix weights")
    metadata = evidence["metadata"]
    name = str(metadata.get("general.name", "")).lower().replace("-", " ")
    if family != "mistral" or model_id != "mistralai/Mistral-7B-Instruct-v0.3":
        raise ValueError("E01A profile is fixed to the preferred Mistral variant")
    if not all(part in name for part in ("mistral", "7b", "instruct", "v0.3")):
        raise ValueError("GGUF model variant metadata does not match the profile")
    if metadata.get("general.architecture") != "llama":
        raise ValueError("Expected llama.cpp Mistral architecture")
    if not metadata.get("tokenizer.ggml.model") or not metadata.get("tokenizer.ggml.tokens"):
        raise ValueError("Embedded tokenizer required")
    if not isinstance(metadata.get("tokenizer.chat_template"), str) or not metadata["tokenizer.chat_template"].strip():
        raise ValueError("Embedded chat template required; no implicit template substitution")


def require_mistral_structure(evidence: dict) -> None:
    """Reject an incomplete/tiny model with a misleading general.name field."""
    metadata = evidence["metadata"]
    required = {"llama.block_count": 32, "llama.embedding_length": 4096,
                "llama.feed_forward_length": 14336, "llama.attention.head_count": 32,
                "llama.attention.head_count_kv": 8}
    if any(metadata.get(key) != value for key, value in required.items()):
        raise ValueError("Mistral-7B-v0.3 architecture metadata mismatch")
    if metadata["tokenizer.ggml.tokens"].get("count") != 32768:
        raise ValueError("Mistral-v3 vocabulary mismatch")
    expected = {"token_embd.weight": [4096, 32768], "output.weight": [4096, 32768],
                "output_norm.weight": [4096]}
    layer = {"attn_q.weight": [4096, 4096], "attn_k.weight": [4096, 1024],
             "attn_v.weight": [4096, 1024], "attn_output.weight": [4096, 4096],
             "attn_norm.weight": [4096], "ffn_norm.weight": [4096],
             "ffn_gate.weight": [4096, 14336], "ffn_up.weight": [4096, 14336],
             "ffn_down.weight": [14336, 4096]}
    for index in range(32):
        expected.update({f"blk.{index}.{key}": shape for key, shape in layer.items()})
    actual = {tensor["name"]: tensor["shape"] for tensor in evidence["tensors"]}
    if actual != expected:
        raise ValueError("Mistral checkpoint tensor set/shapes incomplete or incompatible")
