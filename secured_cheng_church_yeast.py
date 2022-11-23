import time
#from biclustlib.algorithms import SecuredChengChurchAlgorithm
from biclustlib.algorithms import SecuredChengChurchAlgorithmType2
from biclustlib.datasets import load_yeast_tavazoie
import numpy as np

m0 = time.perf_counter()

# load yeast data used in the original Cheng and Church's paper
data = load_yeast_tavazoie().values

# DATA GENERATION
num_rows, num_cols = data.shape
n_elements = num_rows*num_cols
np.random.seed(42)          # Fixed seed for reproducibility
#data = np.random.randint(0, 5, size=(num_rows, num_cols))   # Generate data

# missing value imputation suggested by Cheng and Church
missing = np.where(data < 0.0)
data[missing] = np.random.randint(low=0, high=800, size=len(missing[0]))

# creating an instance of the SecuredChengChurchAlgorithm class and running with the parameters
secca = SecuredChengChurchAlgorithmType2(num_biclusters=num_rows, msr_threshold=300.0, multiple_node_deletion_threshold=1.2)
biclustering = secca.run(data)
print(biclustering)

m1 = time.perf_counter()
print("Time Performance in Calculating Homomorphically: ", m1 - m0, "Seconds")


