import tensorflow as tf

import src.model.network.layer_util as layer_util


class Deconv3D(tf.keras.layers.Layer):
    def __init__(self, filters, output_shape=None, kernel_size=3, strides=1, padding="same", **kwargs):
        """

        :param filters:
        :param output_shape: [out_dim1, out_dim2, out_dim3]
        :param kernel_size:
        :param strides:
        :param padding:
        :param kwargs:
        """
        super(Deconv3D, self).__init__(**kwargs)
        # save parameters
        self._filters = filters
        self._output_shape = output_shape
        self._kernel_size = kernel_size
        self._strides = strides
        self._padding = padding
        self._kwargs = kwargs
        # init layer variables
        self._output_padding = None
        self._Conv3DTranspose = None

    def build(self, input_shape):
        super(Deconv3D, self).build(input_shape)

        if isinstance(self._kernel_size, int):
            self._kernel_size = [self._kernel_size] * 3
        if isinstance(self._strides, int):
            self._strides = [self._strides] * 3

        if self._output_shape is not None:
            """
            https://github.com/tensorflow/tensorflow/blob/1cf0898dd4331baf93fe77205550f2c2e6c90ee5/tensorflow/python/keras/utils/conv_utils.py#L139-L185
            When the output shape is defined, the padding should be calculated manually
            if padding == 'same':
                pad = filter_size // 2
            length = ((input_length - 1) * stride + filter_size - 2 * pad + output_padding)
            """
            self._padding = "same"
            self._output_padding = [
                self._output_shape[i] - ((input_shape[1 + i] - 1) * self._strides[i]
                                         + self._kernel_size[i] - 2 * (self._kernel_size[i] // 2))
                for i in range(3)]
        self._Conv3DTranspose = tf.keras.layers.Conv3DTranspose(filters=self._filters,
                                                                kernel_size=self._kernel_size,
                                                                strides=self._strides,
                                                                padding=self._padding,
                                                                output_padding=self._output_padding,
                                                                **self._kwargs)

    def call(self, inputs, **kwargs):
        return self._Conv3DTranspose(inputs=inputs)


class Resize3d(tf.keras.layers.Layer):
    def __init__(self, size, method=tf.image.ResizeMethod.BILINEAR, **kwargs):
        """

        :param size: [out_dim1, out_dim2, out_dim3], list or tuple
        :param method:
        :param kwargs:
        """
        super(Resize3d, self).__init__(**kwargs)
        # save parameters
        self._size = size
        self._method = method

    def call(self, inputs, **kwargs):
        """
        tensorflow does not have resize 3d, therefore the resize is performed two folds.
        - resize dim2 and dim3
        - resize dim1 and dim2
        :param inputs: shape = [batch, dim1, dim2, dim3, channels], assuming channels_last
        :return:
        """

        input_shape = inputs.shape

        # merge axis 0 and 1
        output = tf.reshape(inputs, [input_shape[0] * input_shape[1],
                                     input_shape[2], input_shape[3],
                                     input_shape[4]])  # [batch * dim1, dim2, dim3, channels]
        # resize dim2 and dim3
        output = tf.image.resize(images=output,
                                 size=[self._size[1], self._size[2]],
                                 method=self._method)  # [batch * dim1, out_dim2, out_dim3, channels]

        # split axis 0 and merge axis 3 and 4
        output = tf.reshape(output,
                            shape=[input_shape[0], input_shape[1], self._size[1],
                                   self._size[2] * input_shape[4]])  # [batch, dim1, out_dim2, out_dim3 * channels]
        # resize dim1 and dim2
        output = tf.image.resize(images=output,
                                 size=[self._size[0], self._size[1]],
                                 method=self._method)  # [batch, out_dim1, out_dim2, out_dim3 * channels]
        # reshape
        output = tf.reshape(output,
                            shape=[input_shape[0], self._size[0], self._size[1], self._size[2],
                                   input_shape[4]])  # [batch, out_dim1, out_dim2, out_dim3, channels]
        return output


class Conv3dBlock(tf.keras.layers.Layer):
    def __init__(self, filters, kernel_size=3, strides=1, padding="same", **kwargs):
        super(Conv3dBlock, self).__init__(**kwargs)
        # init layer variables
        self._conv3d = layer_util.conv3d(filters=filters,
                                         kernel_size=kernel_size,
                                         strides=strides,
                                         padding=padding)
        self._batch_norm = layer_util.batch_norm()
        self._relu = layer_util.act(identifier="relu")

    def call(self, inputs, training=None, **kwargs):
        output = self._conv3d(inputs=inputs)
        output = self._batch_norm(inputs=output, training=training)
        output = self._relu(inputs=output)
        return output


class Deconv3dBlock(tf.keras.layers.Layer):
    def __init__(self, filters, output_shape=None, kernel_size=3, strides=1, padding="same", **kwargs):
        """

        :param filters:
        :param output_shape: [out_dim1, out_dim2, out_dim3]
        :param kernel_size:
        :param strides:
        :param padding:
        :param kwargs:
        """
        super(Deconv3dBlock, self).__init__(**kwargs)
        # init layer variables
        self._deconv3d = Deconv3D(filters=filters,
                                  output_shape=output_shape,
                                  kernel_size=kernel_size,
                                  strides=strides,
                                  padding=padding)
        self._batch_norm = layer_util.batch_norm()
        self._relu = layer_util.act(identifier="relu")

    def call(self, inputs, training=None, **kwargs):
        output = self._deconv3d(inputs=inputs)
        output = self._batch_norm(inputs=output, training=training)
        output = self._relu(inputs=output)
        return output


class AdditiveUpSampling(tf.keras.layers.Layer):
    def __init__(self, output_shape, stride=2, **kwargs):
        """
        :param output_shape: [out_dim1, out_dim2, out_dim3]
        :param stride:
        :param kwargs:
        """
        super(AdditiveUpSampling, self).__init__(**kwargs)
        # save parameters
        self._stride = stride
        # init layer variables
        self._resize3d = Resize3d(size=output_shape)

    def call(self, inputs, **kwargs):
        """
        :param inputs: shape = [batch, dim1, dim2, dim3, channels]
        :param kwargs:
        :return:
        """
        if inputs.shape[4] % self._stride != 0:
            raise ValueError("The channel dimension can not be divided by the stride")
        output = self._resize3d(inputs=inputs)
        output = tf.split(output,
                          num_or_size_splits=self._stride,
                          axis=4)  # a list of [batch, out_dim1, out_dim2, out_dim3, channels//stride], num = stride
        output = tf.reduce_sum(tf.stack(output, axis=5),
                               axis=5)  # [batch, out_dim1, out_dim2, out_dim3, channels//stride]
        return output


class DownSampleResnetBlock(tf.keras.layers.Layer):
    def __init__(self, filters, kernel_size=3, use_pooling=True, **kwargs):
        super(DownSampleResnetBlock, self).__init__(**kwargs)
        # save parameters
        self._use_pooling = use_pooling
        # init layer variables
        self._conv3d_block1 = Conv3dBlock(filters=filters, kernel_size=kernel_size)
        self._conv3d_block2 = Conv3dBlock(filters=filters, kernel_size=kernel_size)
        self._conv3d = layer_util.conv3d(filters=filters, kernel_size=kernel_size, strides=1)
        self._batch_norm = layer_util.batch_norm()
        self._relu = layer_util.act(identifier="relu")
        self._max_pool3d = layer_util.max_pool3d(pool_size=(2, 2, 2), strides=(2, 2, 2))
        self._conv3d_block3 = Conv3dBlock(filters=filters, kernel_size=kernel_size, strides=2)

    def call(self, inputs, training=None, **kwargs):
        h0 = self._conv3d_block1(inputs=inputs, training=training)
        r1 = self._conv3d_block2(inputs=h0, training=training)
        r2 = self._relu(inputs=self._batch_norm(inputs=self._conv3d(inputs=r1),
                                                training=training) + h0)
        h1 = self._max_pool3d(inputs=r2) if self._use_pooling else self._conv3d_block3(inputs=r2, training=training)
        return h1, h0


class UpSampleResnetBlock(tf.keras.layers.Layer):
    def __init__(self, filters, use_additive_upsampling=True, **kwargs):
        super(UpSampleResnetBlock, self).__init__(**kwargs)
        # save parameters
        self._filters = filters
        self._use_additive_upsampling = use_additive_upsampling
        # init layer variables
        self._deconv3d_block = None
        self._additive_upsampling = None
        self._conv3d_block = Conv3dBlock(filters=filters)
        self._conv3d = layer_util.conv3d(filters=filters, strides=1)
        self._batch_norm = layer_util.batch_norm()
        self._relu = layer_util.act(identifier="relu")

    def build(self, input_shape):
        # sanity check
        if not isinstance(input_shape, list):
            raise ValueError("UpSampleResnetBlock accepts an input, a list of tensors [input_nonskip, input_skip]")
        if len(input_shape) != 2:
            raise ValueError("UpSampleResnetBlock accepts an input, a list of tensors [input_nonskip, input_skip]")

        super(UpSampleResnetBlock, self).build(input_shape)

        output_shape = input_shape[1][1:4]
        self._deconv3d_block = Deconv3dBlock(filters=self._filters, output_shape=output_shape, strides=2)
        if self._use_additive_upsampling:
            self._additive_upsampling = AdditiveUpSampling(output_shape=output_shape)

    def call(self, inputs, training=None, **kwargs):
        # sanity check
        if not isinstance(inputs, list):
            raise ValueError("UpSampleResnetBlock accepts an input, a list of tensors [input_nonskip, input_skip]")
        if len(inputs) != 2:
            raise ValueError("UpSampleResnetBlock accepts an input, a list of tensors [input_nonskip, input_skip]")

        inputs_nonskip, inputs_skip = inputs[0], inputs[1]
        h0 = self._deconv3d_block(inputs=inputs_nonskip, training=training)
        if self._use_additive_upsampling:
            h0 += self._additive_upsampling(inputs=inputs_nonskip)
        r1 = h0 + inputs_skip
        r2 = self._conv3d_block(inputs=h0, training=training)
        h1 = self._relu(inputs=self._batch_norm(inputs=self._conv3d(inputs=r2),
                                                training=training) + r1)
        return h1


class DDFSummand(tf.keras.layers.Layer):
    def __init__(self, output_shape, filters=3, **kwargs):
        super(DDFSummand, self).__init__(**kwargs)
        # save parameters
        self._output_shape = output_shape
        # init layer variables
        self._conv3d = layer_util.conv3d(filters=filters, strides=1)
        self._resize3d = Resize3d(size=output_shape)

    def call(self, inputs, **kwargs):
        output = self._conv3d(inputs=inputs)
        if inputs.shape != self._output_shape:  # TODO data type?
            output = self._resize3d(inputs=output)
        return output