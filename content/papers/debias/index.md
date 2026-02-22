---
title: "De-Biasing Generative Models using Counterfactual Methods"
date: 2022-07-01
tags: ["fairness","debiasing","generative models","counterfactual reasoning","causal ML","VAE"]
author: ["Sunay Bhat", "Jeffrey Jiang", "Omead Pooladzandi", "Gregory Pottie"]
description: "Causal Counterfactual Generative Model (CCGM) is a VAE-based framework with a partially trainable causal layer that learns causal relationships, enabling de-biased dataset generation from biased training data."
summary: "CCGM combines a causal latent space VAE with modifications for causal fidelity to generate de-biased datasets from biased training data, offering fine-grained control over causal structure in both image and tabular data generation."
cover:
    image: "debias.png"
    alt: "De-Biasing Generative Models via Counterfactual Methods"
    relative: true
editPost:
    URL: "https://arxiv.org/abs/2207.01575"
    Text: "arXiv 2207.01575"
---

---

##### Download

+ [Paper](https://arxiv.org/abs/2207.01575)

---

##### Abstract

Causal Counterfactual Generative Model (CCGM) is a VAE-based framework with a partially trainable causal layer that learns causal relationships without compromising reconstruction fidelity, allowing for bias analysis, interventions, and scenario simulations. Our method combines a causal latent space VAE model with modifications for causal fidelity, generating de-biased datasets from biased training data and offering finer control over the causal layer, as demonstrated by high-fidelity image and tabular data generation aligned with the causal framework.

---

##### Citation

Bhat, Sunay, Jeffrey Jiang, Omead Pooladzandi, and Gregory Pottie. 2022. "De-biasing Generative Models using Counterfactual Methods." *arXiv preprint arXiv:2207.01575*.

```latex
@article{bhat2022debias,
  title={De-biasing Generative Models using Counterfactual Methods},
  author={Bhat, Sunay and Jiang, Jeffrey and Pooladzandi, Omead and Pottie, Gregory},
  journal={arXiv preprint arXiv:2207.01575},
  year={2022}
}
```
