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

from torch import nn

from nemo.collections.llm import fn


class MockModule(nn.Module, fn.FNMixin):
    def __init__(self):
        super().__init__()
        self.layer1 = nn.Linear(10, 10)
        self.layer2 = nn.Linear(10, 10)


class TestFNMixin:
    def setup_method(self):
        """
        Setup common test resources.
        """
        self.model = MockModule()

    def test_forall_true(self):
        """
        Test `forall` method returns True when the predicate holds for all modules.
        """
        assert self.model.forall(lambda module: isinstance(module, nn.Module), recurse=True)

    def test_forall_false(self):
        """
        Test `forall` method returns False when the predicate does not hold for all modules.
        """
        assert not self.model.forall(lambda module: isinstance(module, nn.Conv2d), recurse=True)

    def test_map(self):
        """
        Test `map` method applies a function to each module.
        """

        def walk_fn(mod):
            if isinstance(mod, nn.Linear):
                mod.weight.data.fill_(1.0)

            return mod

        model = self.model.map(walk_fn, leaf_only=True)
        for layer in [model.layer1, model.layer2]:
            assert (layer.weight.data == 1).all(), "Expected all weights to be set to 1."

    def test_walk(self):
        """
        Test `walk` method traverses each module without modifying them.
        """
        call_count = 0

        def walk_fn(mod):
            nonlocal call_count
            call_count += 1

            return mod

        self.model.walk(walk_fn, leaf_only=True)
        assert call_count == 2, "Expected the function to be called on each leaf module."

    def test_freeze(self):
        """
        Test `freeze` method sets `requires_grad` to False for all parameters.
        """
        self.model.freeze()
        for param in self.model.parameters():
            assert not param.requires_grad, "Expected all parameters to have `requires_grad` set to False."

    def test_unfreeze(self):
        """
        Test `unfreeze` method sets `requires_grad` to True for all parameters.
        """
        self.model.freeze()  # First, freeze all parameters
        self.model.unfreeze()  # Then, unfreeze them
        for param in self.model.parameters():
            assert param.requires_grad, "Expected all parameters to have `requires_grad` set to True."
