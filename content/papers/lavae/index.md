---
title: "Towards Composable Distributions of Latent Space Augmentations"
date: 2023-03-01
tags: ["generative models","VAE","latent space","data augmentation","representation learning"]
author: ["Omead Pooladzandi", "Jeffrey Jiang", "Sunay Bhat", "Gregory Pottie"]
description: "We propose a composable framework for latent space image augmentation based on the VAE architecture, enabling combination of multiple augmentations via linear transformations in the latent space."
summary: "A composable latent space augmentation framework using VAEs that allows augmentations to be combined through linear transformations, preserving specific augmentation variances and improving geometric interpretability over standard and Conditional VAEs."
cover:
    image: "lavae.png"
    alt: "Composable Latent Space Augmentations"
    relative: true
editPost:
    URL: "https://arxiv.org/abs/2303.03462"
    Text: "arXiv 2303.03462"
---

---

##### Download

+ [Paper](https://arxiv.org/abs/2303.03462)

---

##### Abstract

We propose a composable framework for latent space image augmentation, based on the Variational Autoencoder (VAE) architecture, that allows for easy combination of multiple augmentations through linear transformations within the latent space. This method explores losses and augmentation latent geometry to ensure transformations are composable and involuntary, enabling combinations or inversions, and effectively constrains the VAE's bottleneck to preserve specific augmentation variances and image features. We demonstrate improved control and geometric interpretability of the latent space compared to standard and Conditional VAEs on the MNIST dataset.

---

##### Citation

Pooladzandi, Omead, Jeffrey Jiang, Sunay Bhat, and Gregory Pottie. 2023. "Towards Composable Distributions of Latent Space Augmentations." *arXiv preprint arXiv:2303.03462*.

```latex
@article{pooladzandi2023composable,
  title={Towards Composable Distributions of Latent Space Augmentations},
  author={Pooladzandi, Omead and Jiang, Jeffrey and Bhat, Sunay and Pottie, Gregory},
  journal={arXiv preprint arXiv:2303.03462},
  year={2023}
}
```
