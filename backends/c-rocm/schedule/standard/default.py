# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import numpy as np
from tvm import te
import logging
import sys, time, subprocess
import json
import os

def _schedule_single(attrs, output, op_name, have_tail):
  s = attrs.scheduler

  def cache_local(output):
    if not have_tail:
      OL = s.cache_write(output, 'local')
    else:
      s[output].set_scope('local')
      OL, output = output, s.outputs[0].output(0)
    return output, OL
  s.cache_local = cache_local

  num_inputs = len(s[output].op.input_tensors)

  # Rough classification of computing features
  if num_inputs > 1 and len(output.op.reduce_axis) > 0:
    from .algo_tiling import schedule_branch
    return schedule_branch(attrs, output, f"T{op_name}:")

  if not have_tail and len(output.op.reduce_axis) > 0 and not attrs.backend.startswith('c-hlsl_'):
    from .algo_reduce import schedule_branch
    return schedule_branch(attrs, output, f"R{op_name}:")

  from .algo_format import schedule_branch
  return schedule_branch(attrs, output, f"F{op_name}:")

def schedule(attrs):
  config = os.environ.get('CONFIG', '').strip()
  step = int(os.environ.get('STEP', '0'))
  attrs.advanced_sched = config or step > 0
  tail_op, explicit_ops = None, [x for x in attrs.explicit_ops]

  if (len(explicit_ops) > 1 and
      not explicit_ops[-1].output(0).op.reduce_axis and
      len(explicit_ops[-1].output(0).op.input_tensors) > 1):
    fuse_tail = attrs.auto_config.define_knob(f"FU", [False, True])
    if fuse_tail:
      tail_op, explicit_ops = explicit_ops[-1], explicit_ops[:-1]

  for rank, op in enumerate(reversed(explicit_ops)):
    _schedule_single(attrs, op.output(0), op.name, tail_op is not None and rank == 0)
