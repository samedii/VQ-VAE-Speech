 #####################################################################################
 # MIT License                                                                       #
 #                                                                                   #
 # Copyright (C) 2019 Charly Lamothe                                                 #
 #                                                                                   #
 # This file is part of VQ-VAE-Speech.                                               #
 #                                                                                   #
 #   Permission is hereby granted, free of charge, to any person obtaining a copy    #
 #   of this software and associated documentation files (the "Software"), to deal   #
 #   in the Software without restriction, including without limitation the rights    #
 #   to use, copy, modify, merge, publish, distribute, sublicense, and/or sell       #
 #   copies of the Software, and to permit persons to whom the Software is           #
 #   furnished to do so, subject to the following conditions:                        #
 #                                                                                   #
 #   The above copyright notice and this permission notice shall be included in all  #
 #   copies or substantial portions of the Software.                                 #
 #                                                                                   #
 #   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR      #
 #   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,        #
 #   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE     #
 #   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER          #
 #   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,   #
 #   OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE   #
 #   SOFTWARE.                                                                       #
 #####################################################################################

from experiments.experiment import Experiment
from experiments.checkpoint_utils import CheckpointUtils
from experiments.device_configuration import DeviceConfiguration
from error_handling.console_logger import ConsoleLogger
from evaluation.alignment_stats import AlignmentStats

import json
import yaml
import torch
import numpy as np
import random
import os
import matplotlib.pyplot as plt
from scipy.signal import savgol_filter
from itertools import cycle


class Experiments(object):

    def __init__(self, experiments, seed):
        self._experiments = experiments
        self._seed = seed

    def train(self):
        Experiments.set_deterministic_on(self._seed)

        for experiment in self._experiments:
            experiment.train()
            torch.cuda.empty_cache() # Release the GPU memory cache

    def evaluate(self, evaluation_options):

        Experiments.set_deterministic_on(self._seed)

        # TODO: put all types of evaluation in evaluation_options, and skip this loop if none of them are set to true
        for experiment in self._experiments:
            experiment.evaluate(evaluation_options)
            torch.cuda.empty_cache() # Release the GPU memory cache
        
        if evaluation_options['compute_clustering_metrics_evolution']:
            all_results_paths = [experiment.results_path for experiment in self._experiments]
            if len(set(all_results_paths)) != 1:
                ConsoleLogger.error('All clustering metric results should be in the same result folder')
                return
            AlignmentStats.compute_clustering_metrics_evolution(
                all_experiments_names=[experiment.name for experiment in self._experiments],
                result_path=self._experiments[0].results_path
            )

    def plot_losses(self, experiments_path, colormap_name='nipy_spectral'):
        all_train_losses = list()
        all_train_perplexities = list()
        all_results_paths = list()
        all_experiments_names = list()
        all_latest_epochs = list()

        for experiment in self._experiments:
            try:
                train_res_losses, train_res_perplexities, latest_epoch = self._retreive_losses_values(experiments_path, experiment)
                all_train_losses.append(train_res_losses)
                all_train_perplexities.append(train_res_perplexities)
                all_results_paths.append(experiment.results_path)
                all_experiments_names.append(experiment.name)
                all_latest_epochs.append(latest_epoch)
            except:
                ConsoleLogger.error("Failed to retreive losses of experiment '{}'".format(experiment.name))

        n_final_losses_colors = len(all_train_losses)
        final_losses_colors = self._get_colors_from_cmap(colormap_name, n_final_losses_colors)

        # for each experiment: final loss + perplexity
        self._plot_loss_and_perplexity_figures(
            all_results_paths,
            all_experiments_names,
            all_train_losses,
            all_train_perplexities,
            all_latest_epochs,
            n_final_losses_colors,
            final_losses_colors
        )

        # merged experiment: merged final losses + merged perplexities
        self._plot_merged_losses_and_perplexities_figure(
            all_results_paths,
            all_experiments_names,
            all_train_losses,
            all_train_perplexities,
            all_latest_epochs,
            n_final_losses_colors,
            final_losses_colors
        )

        # for each experiment: all possible losses
        self._plot_merged_all_losses_figures(
            all_results_paths,
            all_experiments_names,
            all_train_losses,
            all_train_perplexities,
            all_latest_epochs
        )

        # merged losses of a single type in all experiments
        self._plot_merged_all_losses_type(
            all_results_paths,
            all_experiments_names,
            all_train_losses,
            all_train_perplexities,
            all_latest_epochs
        )

    def _retreive_losses_values(self, experiment_path, experiment):
        experiment_name = experiment.name

        ConsoleLogger.status("Searching configuration and checkpoints of experiment '{}' at path '{}'".format(experiment_name, experiment_path))
        configuration_file, checkpoint_files = CheckpointUtils.search_configuration_and_checkpoints_files(
            experiment_path,
            experiment_name
        )

        # Check if a configuration file was found
        if not configuration_file:
            raise ValueError('No configuration file found with name: {}'.format(experiment_name))

        # Check if at least one checkpoint file was found
        if len(checkpoint_files) == 0:
            raise ValueError('No checkpoint files found with name: {}'.format(experiment_name))

        # Load the configuration file
        configuration_path = experiment_path + os.sep + configuration_file
        ConsoleLogger.status("Loading the configuration file '{}'".format(configuration_path))
        configuration = None
        with open(configuration_path, 'r') as file:
            configuration = yaml.load(file)
        
        # Load the device configuration from the configuration state
        device_configuration = DeviceConfiguration.load_from_configuration(configuration)

        ConsoleLogger.status("Merge {} checkpoint losses of experiment '{}'".format(len(checkpoint_files), experiment_name))
        train_res_losses, train_res_perplexities = CheckpointUtils.merge_experiment_losses(
            experiment_path,
            checkpoint_files,
            device_configuration
        )

        return train_res_losses, train_res_perplexities, len(checkpoint_files)

    def _plot_loss_and_perplexity_figures(self, all_results_paths, all_experiments_names, all_train_losses,
        all_train_perplexities, all_latest_epochs, n_colors, colors):
        
        for i in range(len(all_experiments_names)):
            results_path = all_results_paths[i]
            experiment_name = all_experiments_names[i]
            output_plot_path = results_path + os.sep + experiment_name + '_loss-and-perplexity.png'

            train_loss_smooth = self._smooth_curve(all_train_losses[i]['loss'])
            train_perplexity_smooth = self._smooth_curve(all_train_perplexities[i])

            latest_epoch = all_latest_epochs[i]

            train_loss_smooth = np.asarray(train_loss_smooth)
            train_perplexity_smooth = np.asarray(train_perplexity_smooth)
            train_loss_smooth = np.reshape(train_loss_smooth, (latest_epoch, train_loss_smooth.shape[0] // latest_epoch))
            train_perplexity_smooth = np.reshape(train_perplexity_smooth, (latest_epoch, train_perplexity_smooth.shape[0] // latest_epoch))

            fig = plt.figure(figsize=(16, 8))

            ax = fig.add_subplot(1, 2, 1)
            ax = self._plot_fill_between(ax, colors[i], train_loss_smooth, all_experiments_names[i])
            ax = self._configure_ax(ax, title='Smoothed loss', xlabel='Epochs', ylabel='Loss',
                legend=False)

            ax = fig.add_subplot(1, 2, 2)
            ax = self._plot_fill_between(ax, colors[i], train_perplexity_smooth, all_experiments_names[i])
            ax = self._configure_ax(ax, title='Smoothed average codebook usage',
                xlabel='Epochs', ylabel='Perplexity', legend=False)

            fig.savefig(output_plot_path)
            plt.close(fig)

            ConsoleLogger.success("Saved figure at path '{}'".format(output_plot_path))

    def _plot_merged_losses_and_perplexities_figure(self, all_results_paths, all_experiments_names, all_train_losses,
        all_train_perplexities, all_latest_epochs, n_colors, colors):

        latest_epoch = all_latest_epochs[0]
        for i in range(1, len(all_latest_epochs)):
            if all_latest_epochs[i] != latest_epoch:
                raise ValueError('All experiments must have the same number of epochs to merge them')

        results_path = all_results_paths[0]
        experiment_name = 'merged-loss-and-perplexity'
        output_plot_path = results_path + os.sep + experiment_name + '.png'
        
        all_train_loss_smooth = list()
        all_train_perplexity_smooth = list()
        for i in range(len(all_train_perplexities)):
            train_loss_smooth = self._smooth_curve(all_train_losses[i]['loss'])
            train_perplexity_smooth = self._smooth_curve(all_train_perplexities[i])
            all_train_loss_smooth.append(train_loss_smooth)
            all_train_perplexity_smooth.append(train_perplexity_smooth)

        all_train_loss_smooth = np.asarray(all_train_loss_smooth)
        all_train_perplexity_smooth = np.asarray(all_train_perplexity_smooth)
        all_train_loss_smooth = np.reshape(all_train_loss_smooth, (n_colors, latest_epoch, all_train_loss_smooth.shape[1] // latest_epoch))
        all_train_perplexity_smooth = np.reshape(all_train_perplexity_smooth, (n_colors, latest_epoch, all_train_perplexity_smooth.shape[1] // latest_epoch))

        fig = plt.figure(figsize=(16, 8))

        ax = fig.add_subplot(1, 2, 1)
        for i in range(len(all_train_loss_smooth)):
            ax = self._plot_fill_between(ax, colors[i], all_train_loss_smooth[i], all_experiments_names[i])
        ax = self._configure_ax(ax, title='Smoothed loss', xlabel='Epochs', ylabel='Loss',
            legend=True)

        ax = fig.add_subplot(1, 2, 2)
        for i in range(len(all_train_perplexity_smooth)):
            ax = self._plot_fill_between(ax, colors[i], all_train_perplexity_smooth[i], all_experiments_names[i])
        ax = self._configure_ax(ax, title='Smoothed average codebook usage', xlabel='Epochs',
            ylabel='Perplexity', legend=True)

        fig.savefig(output_plot_path)
        plt.close(fig)

        ConsoleLogger.success("Saved figure at path '{}'".format(output_plot_path))

    def _plot_merged_all_losses_figures(self, all_results_paths, all_experiments_names, all_train_losses,
        all_train_perplexities, all_latest_epochs, colormap_name='tab20'):

        latest_epoch = all_latest_epochs[0]
        for i in range(1, len(all_latest_epochs)):
            if all_latest_epochs[i] != latest_epoch:
                raise ValueError('All experiments must have the same number of epochs to merge them')

        results_path = all_results_paths[0]

        all_train_losses_smooth = list()
        for i in range(len(all_train_losses)):
            train_losses_smooth = list()
            train_losses_names = list()
            for key in all_train_losses[i].keys():
                train_loss_smooth = self._smooth_curve(all_train_losses[i][key])
                train_losses_smooth.append(train_loss_smooth)
                train_losses_names.append(key)
            all_train_losses_smooth.append((train_losses_smooth, train_losses_names))

        for i in range(len(all_train_losses_smooth)):
            n_colors = len(all_train_losses[i])
            colors = self._get_colors_from_cmap(colormap_name, n_colors)

            (train_losses_smooth, train_losses_names) = all_train_losses_smooth[i]
            all_train_loss_smooth = np.asarray(train_losses_smooth)
            all_train_loss_smooth = np.reshape(all_train_loss_smooth, (n_colors, latest_epoch, all_train_loss_smooth.shape[1] // latest_epoch))

            fig, ax = plt.subplots(figsize=(8, 8))

            for j in range(len(all_train_loss_smooth)):
                ax = self._plot_fill_between(ax, colors[j], all_train_loss_smooth[j], train_losses_names[j])
            experiment_name = all_experiments_names[i]
            ax = self._configure_ax(ax, title='Smoothed losses of ' + experiment_name, xlabel='Epochs', ylabel='Loss', legend=True)
            output_plot_path = results_path + os.sep + experiment_name + '_merged-losses.png'

            fig.savefig(output_plot_path)
            plt.close(fig)

            ConsoleLogger.success("Saved figure at path '{}'".format(output_plot_path))

    def _plot_merged_all_losses_type(self, all_results_paths, all_experiments_names, all_train_losses,
        all_train_perplexities, all_latest_epochs, colormap_name='tab20'):

        latest_epoch = all_latest_epochs[0]
        for i in range(1, len(all_latest_epochs)):
            if all_latest_epochs[i] != latest_epoch:
                raise ValueError('All experiments must have the same number of epochs to merge them')

        results_path = all_results_paths[0]

        all_train_losses_smooth = dict()
        for i in range(len(all_train_losses)):
            for loss_name in all_train_losses[i].keys():
                if loss_name == 'loss':
                    continue
                if loss_name not in all_train_losses_smooth:
                    all_train_losses_smooth[loss_name] = list()
                all_train_losses_smooth[loss_name].append(self._smooth_curve(all_train_losses[i][loss_name]))

        for loss_name in all_train_losses_smooth.keys():
            n_colors = len(all_train_losses_smooth[loss_name])
            colors = self._get_colors_from_cmap(colormap_name, n_colors)

            train_losses_smooth = all_train_losses_smooth[loss_name]
            all_train_loss_smooth = np.asarray(train_losses_smooth)
            all_train_loss_smooth = np.reshape(all_train_loss_smooth, (n_colors, latest_epoch, all_train_loss_smooth.shape[1] // latest_epoch))

            fig, ax = plt.subplots(figsize=(8, 8))

            for j in range(len(all_train_loss_smooth)):
                ax = self._plot_fill_between(ax, colors[j], all_train_loss_smooth[j], all_experiments_names[j])
            ax = self._configure_ax(ax, title='Smoothed ' + loss_name.replace('_', ' '), xlabel='Epochs', ylabel='Loss', legend=True)
            output_plot_path = results_path + os.sep + loss_name + '.png'

            fig.savefig(output_plot_path)
            plt.close(fig)

            ConsoleLogger.success("Saved figure at path '{}'".format(output_plot_path))

    def _smooth_curve(self, curve_values):
        maximum_window_length = 201
        smoothed_curve_len = len(curve_values)
        smoothed_curve_len = smoothed_curve_len if smoothed_curve_len % 2 == 1 else smoothed_curve_len - 1
        polyorder = 7

        smoothed_curve = savgol_filter(
            curve_values,
            maximum_window_length if smoothed_curve_len > maximum_window_length else smoothed_curve_len,
            polyorder
        )

        return smoothed_curve

    def _configure_ax(self, ax, title=None, xlabel=None, ylabel=None,
        legend=False):
        ax.minorticks_off()
        ax.grid(linestyle='--')
        ax.set_yscale('log')
        if title:
            ax.set_title(title)
        if xlabel:
            ax.set_xlabel(xlabel)
        if ylabel:
            ax.set_ylabel(ylabel)
        if legend:
            ax.legend()
        ax.grid(True)
        ax.margins(x=0)
        return ax

    def _plot_fill_between(self, ax, color, values, label, linewidth=2):
        linecolor = color # TODO: compute a darker linecolor than facecolor
        facecolor = color
        mu = np.mean(values, axis=1)
        sigma = np.std(values, axis=1)
        t = np.arange(len(values))
        ax.plot(t, mu, linewidth=linewidth, label=label, c=linecolor)
        ax.fill_between(t, mu+sigma, mu-sigma, facecolor=facecolor, alpha=0.5)
        return ax

    def _get_colors_from_cmap(self, colormap_name, n_colors):
        return [plt.get_cmap(colormap_name)(1. * i/n_colors) for i in range(n_colors)]

    @staticmethod
    def set_deterministic_on(seed):
        torch.manual_seed(seed)
        torch.cuda.manual_seed(seed)
        np.random.seed(seed)
        random.seed(seed)
        torch.backends.cudnn.deterministic = True

    @staticmethod
    def load(experiments_path):
        experiments = list()
        with open(experiments_path, 'r') as experiments_file:
            experiment_configurations = json.load(experiments_file)

            configuration = None
            with open(experiment_configurations['configuration_path'], 'r') as configuration_file:
                configuration = yaml.load(configuration_file)

            for experiment_configuration_key in experiment_configurations['experiments'].keys():
                experiment = Experiment(
                    name=experiment_configuration_key,
                    experiments_path=experiment_configurations['experiments_path'],
                    results_path=experiment_configurations['results_path'],
                    global_configuration=configuration,
                    experiment_configuration=experiment_configurations['experiments'][experiment_configuration_key],
                )
                experiments.append(experiment)
        
        return Experiments(experiments, experiment_configurations['seed'])
