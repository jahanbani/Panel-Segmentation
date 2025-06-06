"""
Panel train class
"""

import tensorflow as tf
import numpy as np
from tensorflow.keras.preprocessing import image
from tensorflow.keras.layers import Dropout, Dense
from tensorflow.keras.layers import Conv2D, Conv2DTranspose
from tensorflow.keras.layers import concatenate
import matplotlib.pyplot as plt
from tensorflow.keras import backend as K
import glob
import cv2
from os import path
import pandas as pd
from detecto import core, utils
from torchvision import transforms
from random import choices
import torch


panel_seg_model_path = path.join(path.dirname(
    __file__), 'VGG16Net_ConvTranpose_complete.h5')
panel_classification_model_path = path.join(
    path.dirname(__file__), 'VGG16_classification_model.h5')
mounting_classification_model_path = path.join(path.dirname(__file__),
                                               'object_detection_model.pth')


class TrainPanelSegmentationModel():
    '''
    A class for training a deep learning architecture to perform image
    segmentation on satellite images to detect solar arrays in the image.
    '''

    def __init__(self, batch_size, no_epochs, learning_rate):
        self.no_of_epochs = no_epochs
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        # Base VGG16 network
        self.model = tf.keras.applications.VGG16(
            include_top=False, weights='imagenet',  input_shape=(640, 640, 3),
            pooling='max')
        self.layer_dict = dict([(layer.name, layer)
                               for layer in self.model.layers])

    def loadImagesToNumpyArray(self, image_file_path):
        """
        Load in a set of images from a folder into a 4D numpy array,
        with dimensions (number images, 640, 640, 3).

        Parameters
        -----------
        image_file_path: string
            Path to folder where we want to process png images.

        Returns
        -----------
            nparray
            4D numpy array with dimensions
            (number images in folder, 640, 640, 3).
        """
        # Get a list of the images in the folder
        image_file_list = []
        files = glob.glob(image_file_path + "/*")
        for img_file in files:
            image = cv2.imread(img_file)
            image_file_list.append(image)
        # Convert the image_file_list to a 4d numpy array and return it
        img_np_array = np.array(image_file_list)
        return img_np_array

    def diceCoeff(self, y_true, y_pred, smooth=1):
        """
        Accuracy metric is overly optimistic. IOU, dice coefficient are more
        suitable for semantic segmentation tasks. This function is used as the
        metric of similarity between the predicted mask and ground truth.

        Parameters
        -----------
        y_true: nparray float
            the true mask of the image
        y_pred: nparray float
            the predicted mask of the data
        smooth: int
            a parameter to ensure we are not dividing by zero and also a
            smoothing parameter. For back propagation. If the prediction
            is hard threshold to 0 and 1, it is difficult to back
            propagate the dice loss gradient. We add this parameter to
            actually smooth out the loss function, making it differentiable.

        Returns
        -----------
        dice: float
            The metric of similarity between prediction and ground truth
        """
        intersection = K.sum(y_true * y_pred, axis=[1, 2, 3])
        union = K.sum(y_true, axis=[1, 2, 3]) + K.sum(y_pred, axis=[1, 2, 3])
        dice = K.mean((2. * intersection + smooth)/(union + smooth), axis=0)
        return dice

    def diceCoeffLoss(self, y_true, y_pred):
        """
        This function is a loss function that can be used when training
        the segmentation model. This loss function can be used in place
        of binary crossentropy, which is the current loss function in
        the training stage.

        Parameters
        -----------
        y_true: nparray float
            The true mask of the image
        y_pred: nparray float
            The predicted mask of the data

        Returns
        -----------
            float
            The loss metric between prediction and ground truth
        """
        return 1-self.diceCoeff(y_true, y_pred)

    def trainSegmentation(self, train_data, train_mask, val_data, val_mask,
                          model_file_path=panel_seg_model_path):
        """
        This function uses VGG16 as the base network and as a transfer learning
        framework to train a model that segments solar panels from a satellite
        image. It uses the training data and mask to learn how to predict
        the mask of a solar array from a satellite image. It uses the
        validation data to prevent overfitting and to test the prediction on
        the fly. The validation data is also use to validate when to save the
        best model during training.

        Parameters
        -----------
        train_data: nparray float
            This should be the training images.
        train_mask: nparray int/float
            This should be the training images mask - ground truth
        val_data : nparray float
            This should be the validation images
        val_mask : nparray float
            This should be the validation images mask - ground truth

        Notes
        -----
        Hence the dimension of the four variables must be [a,b,c,d]
        where [a] is the number of input images,
        [b,c] are the dimensions of the image - 640 x 640 in this
        case and [d] is 3 - RGB

        Returns
        -----------
        results: tf.keras.fit_generator History object
            This varaiale contains training history and statistics
        custom_model: tf.keras model object
            The final trianed model. Note that this may not be the
            best model as the best model is saved during training
        """
        train_mask = train_mask/np.max(train_mask)
        val_mask = val_mask/np.max(val_mask)
        train_datagen = image.ImageDataGenerator(
            rescale=1./255,
            dtype='float32')
        val_datagen = image.ImageDataGenerator(
            rescale=1./255,
            dtype='float32')
        train_image_generator = train_datagen.flow(
            train_data, train_mask,
            batch_size=self.batch_size)
        val_image_generator = val_datagen.flow(
            val_data, val_mask,
            batch_size=self.batch_size)
        x = self.layer_dict['block5_conv3'].output
        u5 = Conv2DTranspose(512, (2, 2), strides=(2, 2), padding='same')(x)
        u5 = concatenate([u5, self.layer_dict['block4_conv3'].output])
        c5 = Conv2D(512, (3, 3), activation='elu',
                    kernel_initializer='he_normal', padding='same')(u5)
        c5 = Dropout(0.2)(c5)
        c5 = Conv2D(512, (3, 3), activation='elu',
                    kernel_initializer='he_normal', padding='same')(c5)
        u6 = Conv2DTranspose(256, (2, 2), strides=(2, 2), padding='same')(c5)
        u6 = concatenate([u6, self.layer_dict['block3_conv2'].output])
        c6 = Conv2D(256, (3, 3), activation='elu',
                    kernel_initializer='he_normal', padding='same')(u6)
        c6 = Dropout(0.2)(c6)
        c6 = Conv2D(256, (3, 3), activation='elu',
                    kernel_initializer='he_normal', padding='same')(c6)
        u7 = Conv2DTranspose(128, (2, 2), strides=(2, 2), padding='same')(c6)
        u7 = concatenate([u7, self.layer_dict['block2_conv2'].output])
        c7 = Conv2D(128, (3, 3), activation='elu',
                    kernel_initializer='he_normal', padding='same')(u7)
        c7 = Dropout(0.2)(c7)
        c7 = Conv2D(128, (3, 3), activation='elu',
                    kernel_initializer='he_normal', padding='same')(c7)
        u8 = Conv2DTranspose(64, (2, 2), strides=(2, 2), padding='same')(c7)
        u8 = concatenate([u8, self.layer_dict['block1_conv2'].output], axis=3)
        c8 = Conv2D(32, (3, 3), activation='elu',
                    kernel_initializer='he_normal', padding='same')(u8)
        c8 = Dropout(0.1)(c8)
        c8 = Conv2D(32, (3, 3), activation='elu',
                    kernel_initializer='he_normal', padding='same')(c8)
        outputs = Conv2D(1, (1, 1), activation='sigmoid')(c8)
        custom_model = tf.keras.Model(inputs=self.model.input, outputs=outputs)
        # We fix the weights of the VGG16 architecture, You can choose to make
        # those layers trainable too but it will take a long time
        for layer in custom_model.layers[:18]:
            layer.trainable = False
        custom_model.compile(loss='binary_crossentropy',
                             optimizer=tf.keras.optimizers.Adam(
                                 lr=self.learning_rate, epsilon=1e-08),
                             metrics=['accuracy', self.diceCoeff]
                             )
        no_of_training_images = np.shape(train_data)[0]
        no_of_val_images = np.shape(val_data)[0]
        checkpoint = tf.keras.callbacks.ModelCheckpoint(model_file_path,
                                                        monitor='val_loss',
                                                        verbose=1,
                                                        save_best_only=True,
                                                        mode='max')
        # Training the network
        results = custom_model.fit(train_image_generator,
                                   epochs=self.no_of_epochs,
                                   workers=0,
                                   steps_per_epoch=(
                                       no_of_training_images//self.batch_size),
                                   validation_data=val_image_generator,
                                   validation_steps=(
                                       no_of_val_images//self.batch_size),
                                   callbacks=[checkpoint]
                                   )
        return custom_model, results

    def trainPanelClassifier(self, train_path, val_path,
                             model_file_path=panel_classification_model_path):
        """
        This function uses VGG16 as the base network and as a transfer learning
        framework to train a model that predicts the presence of solar panels
        in a satellite image. It uses the training data to learn how to predict
        the presence of a solar array in a satellite image. It uses the
        validation data to prevent overfitting and to test the prediction on
        the fly. The validation data is also use to validate when to save the
        best model during training.

        Parameters
        -----------
        train_path: string
            This is the path to the folder that contains the training images
            Note that the directory must be structured in this format:
                    train_path/
                        ...has panel/
                            ......a_image_1.jpg
                            ......a_image_2.jpg
                        ...no panels/
                            ......b_image_1.jpg
                            ......b_image_2.jpg
        val_path: string
            This is the path to the folder that contains the validation images
            Note that the directory must be structured in this format:
                    val_path/
                        ...has panel/
                            ......a_image_1.jpg
                            ......a_image_2.jpg
                        ...no panels/
                            ......b_image_1.jpg
                            ......b_image_2.jpg

        Returns
        -----------
        results: tf.keras.fit_generator History object
            This varaiale contains training history and statistics
        final_clas_model: tf.keras model object
            The final trianed model. Note that this may not be the
            best model as the best model is saved during training
        """
        class_x = self.layer_dict['global_max_pooling2d'].output
        out1 = Dense(units=512, activation="relu")(class_x)
        out1 = Dropout(0.2)(out1)
        out2 = Dense(units=512, activation="relu")(out1)
        out2 = Dropout(0.2)(out2)
        out_fin = Dense(units=2, activation="softmax")(out2)
        final_class_model = tf.keras.Model(
            inputs=self.model.input, outputs=out_fin)
        for layer in final_class_model.layers[:18]:
            layer.trainable = True
        final_class_model.summary()
        tr_gen = image.ImageDataGenerator(rescale=1./255,
                                          dtype='float32')
        train_data = tr_gen.flow_from_directory(directory=train_path,
                                                target_size=(640, 640),
                                                batch_size=self.batch_size)
        val_data = tr_gen.flow_from_directory(directory=val_path,
                                              target_size=(640, 640),
                                              batch_size=self.batch_size)
        # Get the number of images in the training and validation sets
        no_of_training_images = len(train_data.labels)
        no_of_val_images = len(val_data.labels)
        final_class_model.compile(loss='categorical_crossentropy',
                                  optimizer=tf.keras.optimizers.Adam(
                                      lr=1e-4, epsilon=1e-08),
                                  metrics=['accuracy']
                                  )
        checkpoint = tf.keras.callbacks.ModelCheckpoint(model_file_path,
                                                        monitor='val_accuracy',
                                                        verbose=1,
                                                        save_best_only=True,
                                                        mode='max',
                                                        save_freq='epoch')
        results =\
            final_class_model.fit(x=train_data,
                                  workers=0,
                                  epochs=self.no_of_epochs,
                                  steps_per_epoch=(no_of_training_images //
                                                   self.batch_size),
                                  validation_data=val_data,
                                  validation_steps=(no_of_val_images //
                                                    self.batch_size),
                                  callbacks=[checkpoint])
        return final_class_model, results

    def trainMountingConfigClassifier(self, train_path, val_path,
                                      device=torch.device('cuda')):
        """
        This function uses Faster R-CNN ResNet50 FPN as the base network
        and as a transfer learning framework to train a model that performs
        object detection on the mounting configuration of solar arrays. It
        uses the training data to locate and classify mounting configuration
        of the solar installation. It uses the validation data to prevent
        overfitting and to test the prediction on the fly.

        Parameters
        -----------
        train_path: string
            This is the path to the folder that contains the training images
            Note that the directory must be structured in this format:
                    train_path/
                        ...images/
                            ......a_image_1.png
                            ......a_image_2.png
                        ...annotations/
                            ......b_image_1.xml
                            ......b_image_2.xml
        val_path: string
            This is the path to the folder that contains the validation images
            Note that the directory must be structured in this format:
                    val_path/
                        ...images/
                            ......a_image_1.png
                            ......a_image_2.png
                        ...annotations/
                            ......b_image_1.xml
                            ......b_image_2.xml
        device: string
            This argument is passed to the Model() class in Detecto.
            It determines how to run the model: either on GPU via Cuda
            (default setting), or on CPU. Please note that running the
            model on GPU results in significantly faster training times.

        Returns
        -----------
        model: detecto.core.Model object
            The final trained mounting configuration object detection
            model.
        """
        # Convert the data set combinations (png + xml) to a CSV record.
        val_labels_path = (val_path + '/annotations.csv')
        train_labels_path = (train_path + '/annotations.csv')
        utils.xml_to_csv(train_path + '/annotations/',
                         train_labels_path)
        utils.xml_to_csv(val_path + '/annotations/',
                         val_labels_path)
        # Custom oversampling to balance out our classes
        train_data = pd.read_csv(train_labels_path)
        class_count = pd.Series(train_data['class'].value_counts())
        train_data_resampled = train_data.copy()
        for index, count in class_count.items():
            number_times_resample = class_count.max() - count
            # Randomly sample a class X times
            class_index_list = list(
                train_data[train_data['class'] == index].index)
            # Resample the list with with replacement
            idx_to_duplicate = choices(class_index_list,
                                       k=number_times_resample)
            for idx in idx_to_duplicate:
                dup = train_data.loc[idx]
                # Add to the dataframe
                train_data_resampled = \
                    pd.concat([train_data_resampled, pd.DataFrame([dup])],
                              ignore_index=True)
        # Reindex after all of the duplicates have been added
        train_data_resampled = train_data_resampled.reset_index(drop=True)
        # Re-write the resampled data set
        train_data_resampled.to_csv(train_labels_path, index=False)
        custom_transforms = transforms.Compose([
            transforms.ToPILImage(),
            transforms.Resize(800),
            transforms.ToTensor(),
            utils.normalize_transform()
        ])
        # Load in the training and validation data sets
        dataset = core.Dataset(train_labels_path,
                               train_path + '/images',
                               transform=custom_transforms)
        val_dataset = core.Dataset(val_labels_path,
                                   val_path + '/images')
        # Customize training options
        loader = core.DataLoader(dataset,
                                 batch_size=self.batch_size,
                                 shuffle=True)
        model = core.Model(["ground-fixed",
                            "carport-fixed",
                            "rooftop-fixed",
                            "ground-single_axis_tracker"],
                           device=device)
        losses = model.fit(loader, val_dataset,
                           epochs=self.no_of_epochs,
                           learning_rate=self.learning_rate,
                           verbose=True)
        plt.plot(losses)
        plt.show()
        return model

    def trainingStatistics(self, results, mode):
        """
        This function prints the training statistics such as training
        loss and accuracy and validation loss and accuarcy. The dice
        coefficient was only used for segmentation and not panel
        classification. We use mode to decide if we should print out
        dice coefficient.

        Parameters
        -----------
        results: tf.keras.fit_generator History object
            This is the output of the trained classifier. It contains
            training history.
        mode: int
            If mode = 1, it assumes we want plots for the semantic
            segmentation and also plots the dice coefficient results.
            For any other value of mode, it does not show plots of dice
            coefficients.

        Returns
        -----------
            figures
            Figures based on the model training statistics
        """
        train_accuracy = results.history['accuracy']
        train_loss = results.history['loss']
        if mode == 1:
            train_dice_coef = results.history['diceCoeff']
        validation_metrics = True
        try:
            val_accuracy = results.history['val_accuracy']
            val_loss = results.history['val_loss']
            if mode == 1:
                val_dice_coef = results.history['val_diceCoeff']
        except Exception as e:
            print("No validation metrics available.")
            print(e)
            validation_metrics = False
        if mode == 1:
            plt.plot(train_dice_coef)
            plt.xlabel('Epochs')
            plt.ylabel('Percentage')
            plt.savefig('Train_dice_coef', dpi=300)
            plt.show()
        plt.plot(train_loss)
        plt.xlabel('Epochs')
        plt.ylabel('Percentage')
        plt.savefig('Train_loss', dpi=300)
        plt.show()
        plt.plot(train_accuracy)
        plt.xlabel('Epochs')
        plt.ylabel('Percentage')
        plt.savefig('Train_accuracy', dpi=300)
        plt.show()
        if validation_metrics is True:
            if mode == 1:
                plt.plot(val_dice_coef)
                plt.xlabel('Epochs')
                plt.ylabel('Percentage')
                plt.savefig('VAL_dice_coef', dpi=300)
                plt.show()
            plt.plot(val_loss)
            plt.xlabel('Epochs')
            plt.ylabel('Percentage')
            plt.savefig('VAL_loss', dpi=300)
            plt.show()
            plt.plot(val_accuracy)
            plt.xlabel('Epochs')
            plt.ylabel('Percentage')
            plt.savefig('VAL_accuracy', dpi=300)
            plt.show()
        plt.plot(train_accuracy, label='train_accuracy')
        plt.plot(train_loss, label='train_loss')
        if mode == 1:
            plt.plot(train_dice_coef, label='train_dice_coef')
        plt.xlabel('Epochs')
        plt.ylabel('Percentage')
        plt.legend()
        plt.savefig('Training statistics', dpi=300)
        plt.show()
        if validation_metrics is True:
            plt.plot(val_accuracy, label='val_accuracy')
            plt.plot(val_loss, label='val_loss')
            if mode == 1:
                plt.plot(val_dice_coef, label='val_dice_coef')
            plt.xlabel('Epochs')
            plt.ylabel('Percentage')
            plt.legend()
            plt.savefig('Validation statistics', dpi=300)
            plt.show()
        return
