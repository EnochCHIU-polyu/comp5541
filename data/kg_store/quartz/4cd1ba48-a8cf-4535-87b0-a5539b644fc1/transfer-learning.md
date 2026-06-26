# Transfer Learning

Transfer learning involves taking a model pre-trained on a large dataset (e.g., ImageNet) and adapting it to a new, often smaller, task. Key steps include loading the pre-trained model, freezing some layers, replacing the output layer, and fine-tuning selected layers with a lower learning rate. This approach leverages generic features learned from the source task to improve performance on the target task.

## Related Concepts

- [[fully-connected-layer]]
- [[convolutional-neural-network-cnn]]

## Source References

- Page 7: _TransferLearning1.ImageNetPre-training2.SmallDataset_
- Page 8: _Main steps for transfer learning1. Load a Pre-trained Model 2. Freeze Layers_
