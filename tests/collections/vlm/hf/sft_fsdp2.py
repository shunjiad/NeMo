# Copyright (c) 2025, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from importlib.metadata import version

import fiddle as fdl
import torch
from lightning.pytorch.loggers import WandbLogger
from packaging.version import Version as PkgVersion

from nemo import lightning as nl
from nemo.collections import llm, vlm

DATA_PATH = "/home/TestData/vlm/rdr-items"


def get_torch_version_str():
    import torch

    if hasattr(torch, '__version__'):
        return str(torch.__version__)
    else:
        return version("torch")


def mk_hf_vlm_dataset(processor, mbs, gbs):
    skipped_tokens = vlm.HFAutoModelForImageTextToText.extract_skipped_token_ids(processor)

    def collate_fn(examples, processor):
        def fmt(sample):
            instruction = "Describe accurately the given image."
            conversation = [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": instruction}, {"type": "image", "image": sample["image"]}],
                },
                {"role": "assistant", "content": [{"type": "text", "text": sample["text"]}]},
            ]
            return {"conversation": conversation, "images": [sample['image']]}

        text = []
        images = []
        for example in map(fmt, examples):
            text.append(
                processor.apply_chat_template(
                    example["conversation"],
                    tokenize=False,
                    add_generation_prompt=False,
                )
            )
            images += example['images']

        # Tokenize the text and process the images
        batch = processor(
            text=text,
            images=images,
            padding=True,
            return_tensors="pt",
        )

        batch["pixel_values"] = batch["pixel_values"].to(torch.bfloat16)

        labels = batch["input_ids"].clone()
        labels[torch.isin(labels, skipped_tokens)] = -100
        batch["labels"] = labels
        return batch

    return vlm.HFDatasetDataModule(
        DATA_PATH,
        split="train[:10]",
        micro_batch_size=mbs,
        global_batch_size=gbs,
        collate_fn=lambda x: collate_fn(x, processor=processor),
    )


if __name__ == '__main__':
    if PkgVersion(get_torch_version_str()) >= PkgVersion("2.4"):
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument('--model', default='Qwen/Qwen2-VL-2B-Instruct')
        parser.add_argument('--devices', default=2)
        parser.add_argument('--mbs', default=1)
        parser.add_argument('--gbs', default=1)
        parser.add_argument('--accelerator', default='gpu', choices=['gpu'])
        parser.add_argument('--max-steps', type=int, default=100)
        parser.add_argument('--wandb-project', type=str, default=None)
        parser.add_argument('--disable-ckpt', action='store_false')
        parser.add_argument('--use-4bit', help="Load model in 4bit", action="store_true")
        args = parser.parse_args()

        wandb = None
        if args.wandb_project is not None:
            model = '_'.join(args.model.split('/')[-2:])
            wandb = WandbLogger(
                project=args.wandb_project,
                name=f'{model}_dev{args.devices}_strat_fsdp2',
            )
        grad_clip = None
        use_dist_samp = False
        processor = vlm.HFAutoModelForImageTextToText.configure_processor(args.model)

        llm.api.finetune(
            model=vlm.HFAutoModelForImageTextToText(args.model, load_in_4bit=args.use_4bit),
            data=mk_hf_vlm_dataset(processor, args.mbs, args.gbs),
            trainer=nl.Trainer(
                devices=args.devices,
                max_steps=args.max_steps,
                accelerator=args.accelerator,
                strategy=nl.FSDP2Strategy(data_parallel_size=2, tensor_parallel_size=1),
                log_every_n_steps=1,
                limit_val_batches=0.0,
                num_sanity_val_steps=0,
                accumulate_grad_batches=2,
                gradient_clip_val=grad_clip,
                use_distributed_sampler=use_dist_samp,
                logger=wandb,
                enable_checkpointing=args.disable_ckpt,
            ),
            optim=fdl.build(llm.adam.pytorch_adam_with_flat_lr(lr=1e-5)),
            log=None,
        )
