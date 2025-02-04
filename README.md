# Research Paper Classification Model

## Repository Overview

This repository contains my implementation of a research paper classification system that I designed to categorize papers as either 'Publishable' or 'Non-Publishable' and assign them to relevant conferences. I utilized advanced natural language processing (NLP) techniques such as SciBERT and RoBERTa to ensure high classification accuracy and efficient resource utilization. The commits for this project are available on the **master branch**.

## Executive Summary

My implemented paper classification system achieves notable performance metrics despite working with a limited dataset:

- **Overall Accuracy**: 86.7%
- **F1 Score**: 92%
- **Conference Assignment Accuracy**: 60% (due to small dataset)
- **Processing Time**: ~29 seconds per batch
- **Resource Utilization**: 1.9GB RAM, 2.7GB GPU memory

The model is designed for scalability and efficiency, focusing on high-performance classification and conference assignment tasks.

## Model Architecture and Implementation

### Core Components:
1. **SciBERT Embeddings**: I used SciBERT for generating high-quality embeddings specifically for scientific papers.
2. **Vector Store Integration**: Implemented using Pathway to perform efficient similarity searches, allowing me to compare document embeddings quickly.
3. **RoBERTa-based QA Model**: I fine-tuned a RoBERTa-based QA model to provide detailed rationales for conference selection based on the paper content.
4. **Cross-Validation Framework**: I employed a 5-fold cross-validation framework to ensure reliable performance evaluation and reduce overfitting.

### Technical Innovations:
1. **Sophisticated Embedding Pipeline**: I optimized SciBERT embeddings with mean pooling, leveraging GPU acceleration for improved performance.
2. **Advanced Similarity Search**: Implemented a vector store for efficient top-k similarity searches with multithreading to speed up retrieval.
3. **Intelligent Conference Assignment**: I ensured context-aware matching for conference assignments by utilizing confidence scores for reliable decisions.

## Performance Analysis

### 1. Classification Metrics:
- **Publishability Assessment**: 86.7% accuracy and 92% F1 score.
- **Conference Assignment**: 60% accuracy (due to small dataset size).

### 2. Resource Efficiency:
- **Processing Time**: ~29 seconds per batch, averaging 0.125 seconds per operation.
- **Memory Usage**: 1.9GB RAM, 2.7GB GPU memory usage.

### 3. Scalability:
- The system maintains performance consistency with higher computational loads, thanks to GPU acceleration.

## Small Dataset Challenges and Mitigations

### 1. Dataset Characteristics:
- I worked with a small number of reference papers per conference.
- The validation set was small, with only a few papers per fold, and conference-specific examples varied significantly.

### 2. Mitigations:
- **Feature Engineering**: I optimized text extraction from PDFs, focusing on key sections such as the title, abstract, and keywords.
- **Model Design**: The embedding-based similarity search worked well to generalize to unseen papers.
- **Performance Optimization**: I leveraged GPU acceleration to minimize computation time and memory usage.

## Model Strengths

1. **Technical Robustness**: With strong metrics (86.7% accuracy, 92% F1 score), the model shows reliability and scalability.
2. **Implementation Quality**: The modular design of the code allows for easy maintenance and future improvements. Comprehensive error handling ensures stability.
3. **Feature Innovation**: I used advanced embedding techniques and context-aware conference matching to improve classification performance.



