# Gradient Flow

Gradient flow refers to the propagation of gradients during backpropagation, which is essential for updating network weights via optimization algorithms like SGD. The choice of activation function critically influences gradient flow; functions that saturate (e.g., Sigmoid) can cause gradients to vanish, while non-saturating ones (e.g., ReLU) help maintain stronger gradients, facilitating deeper network training.

## Related Concepts

- [[vanishing-gradient-problem]]
- [[activation-function]]

## Source References

- Page 16: _Theactivationfunctionaffectsgradientflow_
- Page 17: _𝜕𝐿𝜕𝑤1=𝜕𝐿𝜕𝑦𝜕𝑦𝜕𝑧𝜕𝑧𝜕𝑤1_
