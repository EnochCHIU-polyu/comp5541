# Sigmoid Activation

The Sigmoid activation function squashes input values into the range [0,1], making it historically popular for interpreting outputs as probabilities or biological neuron firing rates. However, it suffers from saturation, where gradients become very small (vanishing gradient problem), which can halt learning in deep networks by preventing weight updates.

## Related Concepts

- [[vanishing-gradient-problem]]
- [[activation-function]]

## Source References

- Page 18: _Sigmoid •Mathematically,itsquashes numbers to range [0,1]_
- Page 19: _ProblemsforSigmoidFunction1.Saturated neurons “kill” the gradients_
