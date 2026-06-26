# Gradient Flow

Gradient flow refers to the propagation of gradients through the network during backpropagation. The activation function's derivative (local gradient) directly impacts this flow. Poor gradient flow, such as vanishing gradients, can stall learning in deep networks.

## Related Concepts

- [[activation-function]]
- [[vanishing-gradient-problem]]

## Source References

- Page 16: _Theactivationfunctionaffectsgradientflow_
- Page 17: _𝜕𝐿/𝜕𝑤1=𝜕𝐿/𝜕𝑦 𝑓′(𝑧) 𝑥1_
