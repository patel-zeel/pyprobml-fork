# Multi-armed bandit problem for a linear Gaussian model
# with linear reward function.
# In this demo, we consider three arms:
# 1. The first arm is an upward-trending arm with initial negative bias
# 2. The second arm is a downward-trending arm with initial positive bias
# 3. The third arm is a stationary arm with initial zero bias
# !pip install -Uq tfp-nightly[jax] > /dev/null

# Author: Gerardo Durán-Martín (@gerdm)

import superimport

import jax
import seaborn as sns
import matplotlib.pyplot as plt
import pyprobml_utils as pml
import jax.numpy as jnp
import pandas as pd
from jax import random
from functools import partial
from jax.ops import index_update
from jax.nn import one_hot
from tensorflow_probability.substrates import jax as tfp
tfd = tfp.distributions


class NormalGammaBandit:
    def sample(self, key, params, state):
        key_sigma, key_w = random.split(key, 2)
        sigma2_samp = tfd.InverseGamma(concentration=params["a"], scale=params["b"]).sample(seed=key_sigma)
        cov_matrix_samples = sigma2_samp[:, None, None] * params["Sigma"]
        w_samp = tfd.MultivariateNormalFullCovariance(loc=params["mu"], covariance_matrix=cov_matrix_samples).sample(seed=key_w)
        return sigma2_samp, w_samp
        
    def predict_rewards(self, params_sample, state):
        sigma2_samp, w_samp = params_sample
        predicted_reward = jnp.einsum("m,km->k", state, w_samp)
        return predicted_reward
        
    def update(self, action, params, state, reward):
        """
        Update the parameters of the model for the
        chosen arm
        """
        mu_k = params["mu"][action]
        Sigma_k = params["Sigma"][action]
        Lambda_k = jnp.linalg.inv(Sigma_k)
        a_k = params["a"][action]
        b_k = params["b"][action]
        
        # weight params
        Lambda_update = jnp.outer(state, state) + Lambda_k
        Sigma_update = jnp.linalg.inv(Lambda_update)
        mu_update = Sigma_update @ (Lambda_k @ mu_k + state * reward)
        # noise params
        a_update = a_k + 1/2
        b_update = b_k + (reward ** 2 + mu_k.T @ Lambda_k @ mu_k - mu_update.T @ Lambda_update @ mu_update) / 2
        
        # Update only the chosen action at time t
        mu = index_update(params["mu"], action, mu_update)
        Sigma = index_update(params["Sigma"], action, Sigma_update)
        a = index_update(params["a"], action, a_update)
        b = index_update(params["b"], action, b_update)
        
        params = {
            "mu": mu,
            "Sigma": Sigma,
            "a": a,
            "b": b
        }
        
        return params
    

def true_reward(key, action, state, true_params):
    """
    Compute true reward as the linear combination
    of each set of weights and the observed state plus
    the noise from each arm
    """
    w_k = true_params["w"][action]
    sigma_k = jnp.sqrt(true_params["sigma2"][action])
    reward = w_k @ state + random.normal(key) * sigma_k
    return reward


def thompson_sampling_step(model_params, state, model, environment):
    """
    Contextual implementation of the Thompson sampling algorithm.
    This implementation considers a single step
    
    Parameters
    ----------
    model_params: dict
    environment: function
    key: jax.random.PRNGKey
    moidel: instance of a Bandit model
    """
    key, context = state
    key_sample, key_reward = random.split(key)
    # Sample an choose an action
    params = model.sample(key_sample, model_params, context)
    pred_rewards = model.predict_rewards(params, context)
    action = pred_rewards.argmax()
    # environment reward
    reward = environment(key_reward, action, context)
    model_params = model.update(action, model_params, context, reward)
    
    arm_reward = one_hot(action, K) * reward
    return model_params, (model_params, arm_reward)



plt.rcParams["axes.spines.top"] = False
plt.rcParams["axes.spines.right"] = False


# 1. Specify underlying dynamics (unknown)
W = jnp.array([
    [-5.0, 2.0, 0.5],
    [0.0,  0.0, 0.0],
    [5.0, -1.5, -1.0]
])

sigmas = jnp.ones(3)

K, M = W.shape
N = 500
T = 4
x = jnp.linspace(0, T, N)
X = jnp.c_[jnp.ones(N), x, x ** 2]

true_params = {
    "w": W,
    "sigma2": sigmas ** 2
}


# 2. Sample one instance of the multi-armed bandit process
#    this is only for plotting, it will not be used fo training
key = random.PRNGKey(314)
noise = random.multivariate_normal(key, mean=jnp.zeros(K), cov=jnp.eye(K) * sigmas, shape=(N,))
Y = jnp.einsum("nm,km->nk", X, W) + noise


# 3. Configure the model parameters that will be used
# during Thompson sampling
eta = 2.0
lmbda = 5.0
init_params = {
    "mu": jnp.zeros((K, M)),
    "Sigma": lmbda * jnp.eye(M) * jnp.ones((K, 1, 1)),
    "a": eta * jnp.ones(K),
    "b": eta * jnp.ones(K),
}
environment = partial(true_reward, true_params=true_params)
thompson_partial = partial(thompson_sampling_step,
                        model=NormalGammaBandit(),
                        environment=environment)
thompson_vmap = jax.vmap(lambda key: jax.lax.scan(thompson_partial, init_params, (random.split(key, N), X)))


#4. Do Thompson sampling
nsamples = 100
key = random.PRNGKey(3141)
keys = random.split(key, nsamples)
posteriors_samples, (_, hist_reward_samples) = thompson_vmap(keys)


# 5. Plotting
# 5.1 Example dataset
plt.plot(x, Y)
plt.axhline(y=0, c="black")
plt.legend([f"arm{i}" for i in range(K)])
pml.savefig("bandit-lingauss-true-reward.pdf")

# 5.2 Plot heatmap of chosen arm and given reward
ix = 0
map_reward = hist_reward_samples[ix]
map_reward = index_update(map_reward, map_reward==0, jnp.nan)
labels = [f"arm{i}" for i in range(K)]
map_reward_df = pd.DataFrame(map_reward, index=[f"{t:0.2f}" for t in x], columns=labels)

fig, ax = plt.subplots(figsize=(4, 5))
sns.heatmap(map_reward_df, cmap="viridis", ax=ax, xticklabels=labels)
plt.ylabel("time")
pml.savefig("bandit-lingauss-heatmap.pdf")

# 5.3 Plot cumulative reward per arm
fig, ax = plt.subplots()
plt.plot(x, hist_reward_samples[ix].cumsum(axis=0))
plt.legend(labels, loc="upper left")
plt.ylabel("cumulative reward")
plt.xlabel("time")
pml.savefig("bandit-lingauss-cumulative-reward.pdf")

# 5.4 Plot regret
fig, ax = plt.subplots()
expected_hist_reward = hist_reward_samples.mean(axis=0)
optimal_reward = jnp.einsum("nm,km->nk", X, true_params["w"]).max(axis=1)
regret = optimal_reward - expected_hist_reward.max(axis=1)
cumulative_regret = regret.cumsum()


# plt.plot(x, cumulative_regret)
plt.plot(x, cumulative_regret, label='observed')
scale_factor = 20  # empirical
plt.plot(x, scale_factor * jnp.sqrt(x), label='c $\sqrt{t}$')
plt.title("Cumulative regret")
plt.ylabel("$L_T$")
plt.xlabel("time")
plt.legend()
pml.savefig("bandit-lingauss-cumulative-regret.pdf")

plt.show()
